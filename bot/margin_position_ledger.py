from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("nija.margin_position_ledger")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MarginPositionLedger:
    """Canonical margin position ledger (one row per broker+account+subaccount+symbol+asset_class)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        configured = str(db_path or os.getenv("NIJA_MARGIN_POSITION_LEDGER_PATH", "")).strip()
        self._db_path = Path(configured or "./data/margin_position_ledger.db")
        self._lock = threading.Lock()
        self._sync_stop = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_database(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS margin_position_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    subaccount_id TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    position_units REAL NOT NULL DEFAULT 0,
                    position_notional_usd REAL NOT NULL DEFAULT 0,
                    buying_power_usd REAL,
                    available_margin_usd REAL,
                    leverage INTEGER,
                    margin_mode TEXT,
                    reduce_only INTEGER,
                    last_request_id TEXT,
                    last_intent_id TEXT,
                    last_reason TEXT,
                    broker_order_id TEXT,
                    broker_status TEXT,
                    last_broker_sync_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(broker, account_id, subaccount_id, symbol, asset_class)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS margin_position_ledger_applied_ops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    op_type TEXT NOT NULL,
                    request_id TEXT,
                    intent_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mpl_lookup ON margin_position_ledger(broker, account_id, subaccount_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mpl_symbol ON margin_position_ledger(symbol, asset_class)"
            )
            conn.execute(
                "DROP INDEX IF EXISTS idx_mpl_ops_request"
            )
            conn.execute(
                "DROP INDEX IF EXISTS idx_mpl_ops_intent"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mpl_ops_request_type ON margin_position_ledger_applied_ops(op_type, request_id) "
                "WHERE request_id IS NOT NULL AND request_id != ''"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mpl_ops_intent_type ON margin_position_ledger_applied_ops(op_type, intent_id) "
                "WHERE intent_id IS NOT NULL AND intent_id != ''"
            )
            conn.commit()

    @staticmethod
    def _identity_from_request(request: Any) -> Dict[str, str]:
        return {
            "broker": str(getattr(request, "preferred_broker", None) or "coinbase").strip().lower() or "coinbase",
            "account_id": str(getattr(request, "account_id", "default") or "default").strip() or "default",
            "subaccount_id": str(getattr(request, "subaccount_id", "") or "").strip(),
            "symbol": str(getattr(request, "symbol", "") or "").strip().upper(),
            "asset_class": str(getattr(request, "asset_class", None) or "crypto").strip().lower() or "crypto",
        }

    @staticmethod
    def _clean_id(value: Any) -> Optional[str]:
        v = str(value or "").strip()
        return v or None

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
        return dict(row) if row is not None else {}

    def _get_row(self, cursor: sqlite3.Cursor, *, broker: str, account_id: str, subaccount_id: str, symbol: str, asset_class: str) -> Optional[sqlite3.Row]:
        cursor.execute(
            """
            SELECT * FROM margin_position_ledger
            WHERE broker=? AND account_id=? AND subaccount_id=? AND symbol=? AND asset_class=?
            """,
            (broker, account_id, subaccount_id, symbol, asset_class),
        )
        return cursor.fetchone()

    def _ensure_row(self, cursor: sqlite3.Cursor, identity: Dict[str, str], *, lifecycle_status: str) -> sqlite3.Row:
        now = _utc_now()
        cursor.execute(
            """
            INSERT INTO margin_position_ledger (
                broker, account_id, subaccount_id, symbol, asset_class,
                lifecycle_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(broker, account_id, subaccount_id, symbol, asset_class)
            DO NOTHING
            """,
            (
                identity["broker"],
                identity["account_id"],
                identity["subaccount_id"],
                identity["symbol"],
                identity["asset_class"],
                lifecycle_status,
                now,
                now,
            ),
        )
        row = self._get_row(cursor, **identity)
        if row is None:
            raise RuntimeError("failed to initialize margin ledger row")
        return row

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        allowed = {
            "pending_open": {"pending_open", "open", "rejected", "closed"},
            "open": {"pending_open", "open", "reducing", "closed", "rejected"},
            "reducing": {"pending_open", "reducing", "closed", "rejected"},
            "rejected": {"rejected", "pending_open"},
            "closed": {"closed", "pending_open"},
        }
        if target not in allowed.get(current, set()):
            raise ValueError(f"invalid_lifecycle_transition:{current}->{target}")

    def _operation_seen(
        self,
        cursor: sqlite3.Cursor,
        *,
        op_type: str,
        request_id: Optional[str],
        intent_id: Optional[str],
    ) -> bool:
        if request_id:
            cursor.execute(
                "SELECT 1 FROM margin_position_ledger_applied_ops WHERE op_type=? AND request_id=? LIMIT 1",
                (op_type, request_id),
            )
            if cursor.fetchone() is not None:
                return True
        if intent_id:
            cursor.execute(
                "SELECT 1 FROM margin_position_ledger_applied_ops WHERE op_type=? AND intent_id=? LIMIT 1",
                (op_type, intent_id),
            )
            if cursor.fetchone() is not None:
                return True
        return False

    def _record_operation(self, cursor: sqlite3.Cursor, *, op_type: str, request_id: Optional[str], intent_id: Optional[str]) -> None:
        cursor.execute(
            """
            INSERT INTO margin_position_ledger_applied_ops (op_type, request_id, intent_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (op_type, request_id, intent_id, _utc_now()),
        )

    def get_record(
        self,
        *,
        broker: str,
        account_id: str,
        subaccount_id: str,
        symbol: str,
        asset_class: str,
    ) -> Dict[str, Any]:
        identity = {
            "broker": str(broker or "coinbase").strip().lower() or "coinbase",
            "account_id": str(account_id or "default").strip() or "default",
            "subaccount_id": str(subaccount_id or "").strip(),
            "symbol": str(symbol or "").strip().upper(),
            "asset_class": str(asset_class or "crypto").strip().lower() or "crypto",
        }
        with self._connect() as conn:
            row = self._get_row(conn.cursor(), **identity)
            return self._row_to_dict(row)

    def reconcile_snapshot(self, **kwargs: Any) -> Dict[str, Any]:
        return self.reconcile_positions(**kwargs)

    def start_periodic_reconcile(
        self,
        poll_fn: Callable[[], Iterable[Dict[str, Any]]],
        *,
        interval_s: float = 30.0,
    ) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_stop.clear()

        def _worker() -> None:
            while not self._sync_stop.is_set():
                try:
                    snapshots = poll_fn() or []
                    for snapshot in snapshots:
                        try:
                            self.reconcile_positions(**dict(snapshot))
                        except Exception as exc:
                            logger.debug("margin ledger reconcile failed: %s", exc)
                except Exception as exc:
                    logger.debug("margin ledger poll failed: %s", exc)
                self._sync_stop.wait(max(1.0, float(interval_s or 30.0)))

        self._sync_thread = threading.Thread(target=_worker, name="nija-margin-ledger-sync", daemon=True)
        self._sync_thread.start()

    def stop_periodic_reconcile(self) -> None:
        self._sync_stop.set()
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=1.0)
        self._sync_thread = None


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


class MarginPositionTracker:

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
        subaccount_id: str,
        symbol: str,
        asset_class: str,
    ) -> Dict[str, Any]:
        with self._connect() as conn:
            row = self._get_row(
                conn.cursor(),
                broker=str(broker).strip().lower(),
                account_id=str(account_id).strip(),
                subaccount_id=str(subaccount_id or "").strip(),
                symbol=str(symbol).strip().upper(),
                asset_class=str(asset_class).strip().lower(),
            )
            return self._row_to_dict(row)

    def apply_submit(self, request: Any) -> Dict[str, Any]:
        identity = self._identity_from_request(request)
        request_id = self._clean_id(getattr(request, "request_id", None))
        intent_id = self._clean_id(getattr(request, "intent_id", None))
        with self._lock, self._connect() as conn:
            cursor = conn.cursor()
            if self._operation_seen(cursor, op_type="submit", request_id=request_id, intent_id=intent_id):
                return self._row_to_dict(self._get_row(cursor, **identity))

            row = self._ensure_row(cursor, identity, lifecycle_status="pending_open")
            current_state = str(row["lifecycle_status"] or "pending_open")
            self._assert_transition(current_state, "pending_open")

            now = _utc_now()
            cursor.execute(
                """
                UPDATE margin_position_ledger
                SET lifecycle_status=?,
                    buying_power_usd=COALESCE(?, buying_power_usd),
                    available_margin_usd=COALESCE(?, available_margin_usd),
                    leverage=COALESCE(?, leverage),
                    margin_mode=COALESCE(?, margin_mode),
                    reduce_only=?,
                    last_request_id=COALESCE(?, last_request_id),
                    last_intent_id=COALESCE(?, last_intent_id),
                    broker_status='submitted',
                    updated_at=?
                WHERE broker=? AND account_id=? AND subaccount_id=? AND symbol=? AND asset_class=?
                """,
                (
                    "pending_open",
                    getattr(request, "buying_power_usd", None),
                    getattr(request, "available_balance_usd", None),
                    getattr(request, "leverage", None),
                    getattr(request, "margin_mode", None),
                    None if getattr(request, "reduce_only", None) is None else (1 if bool(getattr(request, "reduce_only")) else 0),
                    request_id,
                    intent_id,
                    now,
                    identity["broker"],
                    identity["account_id"],
                    identity["subaccount_id"],
                    identity["symbol"],
                    identity["asset_class"],
                ),
            )
            self._record_operation(cursor, op_type="submit", request_id=request_id, intent_id=intent_id)
            conn.commit()
            return self._row_to_dict(self._get_row(cursor, **identity))

    def apply_ack_fill(self, request: Any, result: Any) -> Dict[str, Any]:
        identity = self._identity_from_request(request)
        request_id = self._clean_id(getattr(request, "request_id", None))
        intent_id = self._clean_id(getattr(request, "intent_id", None))
        with self._lock, self._connect() as conn:
            cursor = conn.cursor()
            if self._operation_seen(cursor, op_type="ack_fill", request_id=request_id, intent_id=intent_id):
                return self._row_to_dict(self._get_row(cursor, **identity))

            row = self._ensure_row(cursor, identity, lifecycle_status="pending_open")
            lifecycle = str(row["lifecycle_status"] or "pending_open")
            if lifecycle == "rejected":
                raise ValueError("invalid_lifecycle_transition:rejected->ack_fill")

            current_notional = float(row["position_notional_usd"] or 0.0)
            current_units = float(row["position_units"] or 0.0)
            filled_notional = max(0.0, float(getattr(result, "filled_size_usd", 0.0) or 0.0))
            filled_units = max(0.0, float(getattr(request, "units", 0.0) or 0.0))
            intent_type = str(getattr(request, "intent_type", "") or "").strip().lower()

            if intent_type in {"reduce", "exit"}:
                next_notional = max(0.0, current_notional - filled_notional)
                next_units = max(0.0, current_units - filled_units)
                next_lifecycle = "closed" if next_notional <= 1e-9 else "reducing"
            else:
                next_notional = current_notional + filled_notional
                next_units = current_units + filled_units
                next_lifecycle = "open" if next_notional > 0 else lifecycle

            self._assert_transition(lifecycle, next_lifecycle)
            now = _utc_now()
            cursor.execute(
                """
                UPDATE margin_position_ledger
                SET lifecycle_status=?,
                    position_units=?,
                    position_notional_usd=?,
                    last_request_id=COALESCE(?, last_request_id),
                    last_intent_id=COALESCE(?, last_intent_id),
                    broker_status=?,
                    updated_at=?
                WHERE broker=? AND account_id=? AND subaccount_id=? AND symbol=? AND asset_class=?
                """,
                (
                    next_lifecycle,
                    next_units,
                    next_notional,
                    request_id,
                    intent_id,
                    "filled" if filled_notional > 0 else "ack",
                    now,
                    identity["broker"],
                    identity["account_id"],
                    identity["subaccount_id"],
                    identity["symbol"],
                    identity["asset_class"],
                ),
            )
            self._record_operation(cursor, op_type="ack_fill", request_id=request_id, intent_id=intent_id)
            conn.commit()
            return self._row_to_dict(self._get_row(cursor, **identity))

    def apply_reject_or_cancel(self, request: Any, reason: str) -> Dict[str, Any]:
        identity = self._identity_from_request(request)
        request_id = self._clean_id(getattr(request, "request_id", None))
        intent_id = self._clean_id(getattr(request, "intent_id", None))
        with self._lock, self._connect() as conn:
            cursor = conn.cursor()
            if self._operation_seen(cursor, op_type="reject_cancel", request_id=request_id, intent_id=intent_id):
                return self._row_to_dict(self._get_row(cursor, **identity))

            row = self._ensure_row(cursor, identity, lifecycle_status="pending_open")
            lifecycle = str(row["lifecycle_status"] or "pending_open")
            current_notional = float(row["position_notional_usd"] or 0.0)
            intent_type = str(getattr(request, "intent_type", "") or "").strip().lower()

            next_lifecycle = "closed" if intent_type in {"reduce", "exit"} and current_notional <= 1e-9 else "rejected"
            self._assert_transition(lifecycle, next_lifecycle)

            cursor.execute(
                """
                UPDATE margin_position_ledger
                SET lifecycle_status=?,
                    last_reason=?,
                    last_request_id=COALESCE(?, last_request_id),
                    last_intent_id=COALESCE(?, last_intent_id),
                    broker_status='rejected',
                    updated_at=?
                WHERE broker=? AND account_id=? AND subaccount_id=? AND symbol=? AND asset_class=?
                """,
                (
                    next_lifecycle,
                    str(reason or "unknown_rejection"),
                    request_id,
                    intent_id,
                    _utc_now(),
                    identity["broker"],
                    identity["account_id"],
                    identity["subaccount_id"],
                    identity["symbol"],
                    identity["asset_class"],
                ),
            )
            self._record_operation(cursor, op_type="reject_cancel", request_id=request_id, intent_id=intent_id)
            conn.commit()
            return self._row_to_dict(self._get_row(cursor, **identity))

    def reconcile_snapshot(
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
        subaccount_id: str,
        symbol: str,
        asset_class: str,
        broker_units: float,
        broker_notional_usd: float,
        buying_power_usd: Optional[float] = None,
        available_margin_usd: Optional[float] = None,
        leverage: Optional[int] = None,
        margin_mode: Optional[str] = None,
        leverage_authoritative: bool = False,
        margin_mode_authoritative: bool = False,
        drift_threshold_usd: float = 0.01,
    ) -> Dict[str, Any]:
        identity = {
            "broker": str(broker or "coinbase").strip().lower() or "coinbase",
            "account_id": str(account_id or "default").strip() or "default",
            "subaccount_id": str(subaccount_id or "").strip(),
            "symbol": str(symbol or "").strip().upper(),
            "asset_class": str(asset_class or "crypto").strip().lower() or "crypto",
        }
        with self._lock, self._connect() as conn:
            cursor = conn.cursor()
            row = self._ensure_row(cursor, identity, lifecycle_status="pending_open")
            local_notional = float(row["position_notional_usd"] or 0.0)
            broker_notional = max(0.0, float(broker_notional_usd or 0.0))
            broker_units_val = max(0.0, float(broker_units or 0.0))
            drift = abs(local_notional - broker_notional)
            corrected = drift > max(0.0, float(drift_threshold_usd or 0.0))

            lifecycle = str(row["lifecycle_status"] or "pending_open")
            next_lifecycle = lifecycle
            if corrected:
                next_lifecycle = "open" if broker_notional > 1e-9 else "closed"
                try:
                    self._assert_transition(lifecycle, next_lifecycle)
                except ValueError:
                    next_lifecycle = "open" if broker_notional > 1e-9 else "closed"
                logger.warning(
                    "margin ledger drift corrected | broker=%s account=%s symbol=%s local=%.6f broker=%.6f drift=%.6f",
                    identity["broker"],
                    identity["account_id"],
                    identity["symbol"],
                    local_notional,
                    broker_notional,
                    drift,
                )

            next_leverage = leverage if leverage_authoritative else row["leverage"]
            next_margin_mode = margin_mode if margin_mode_authoritative else row["margin_mode"]
            cursor.execute(
                """
                UPDATE margin_position_ledger
                SET lifecycle_status=?,
                    position_units=?,
                    position_notional_usd=?,
                    buying_power_usd=COALESCE(?, buying_power_usd),
                    available_margin_usd=COALESCE(?, available_margin_usd),
                    leverage=?,
                    margin_mode=?,
                    broker_status=?,
                    last_broker_sync_at=?,
                    updated_at=?
                WHERE broker=? AND account_id=? AND subaccount_id=? AND symbol=? AND asset_class=?
                """,
                (
                    next_lifecycle,
                    broker_units_val if corrected else float(row["position_units"] or 0.0),
                    broker_notional if corrected else local_notional,
                    buying_power_usd,
                    available_margin_usd,
                    next_leverage,
                    next_margin_mode,
                    "reconciled" if corrected else "in_sync",
                    _utc_now(),
                    _utc_now(),
                    identity["broker"],
                    identity["account_id"],
                    identity["subaccount_id"],
                    identity["symbol"],
                    identity["asset_class"],
                ),
            )
            conn.commit()
            final_row = self._row_to_dict(self._get_row(cursor, **identity))
            return {
                "corrected": corrected,
                "drift_usd": drift,
                "record": final_row,
            }

    def start_periodic_reconcile(
        self,
        poll_fn: Callable[[], Iterable[Dict[str, Any]]],
        *,
        interval_s: float = 30.0,
    ) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_stop.clear()

        def _worker() -> None:
            while not self._sync_stop.is_set():
                try:
                    snapshots = poll_fn() or []
                    for snapshot in snapshots:
                        try:
                            self.reconcile_snapshot(**dict(snapshot))
                        except Exception as exc:
                            logger.debug("margin ledger reconcile snapshot failed: %s", exc)
                except Exception as exc:
                    logger.debug("margin ledger poll failed: %s", exc)
                self._sync_stop.wait(max(1.0, float(interval_s or 30.0)))

        self._sync_thread = threading.Thread(target=_worker, name="nija-margin-ledger-sync", daemon=True)
        self._sync_thread.start()

    def stop_periodic_reconcile(self) -> None:
        self._sync_stop.set()
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=1.0)
        self._sync_thread = None

    def reconcile_position_tracking(
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
        self.reconcile_snapshot(
            broker=broker,
            account_id=account_id,
            symbol=symbol,
            position_id=pid,
            side=side_lower,
            notional_usd=notional_usd,
            leverage=leverage,
            reduce_only=reduce_only,
        )

    def get_account_risk_snapshot(self, *, broker: str, account_id: str) -> "MarginRiskSnapshot":
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
            logger.debug("MarginPositionTracker load skipped: %s", exc)

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
            logger.debug("MarginPositionTracker persist skipped: %s", exc)


_LEDGER_SINGLETON: Optional[MarginPositionLedger] = None
_LEDGER_SINGLETON_LOCK = threading.Lock()


def get_margin_position_ledger(db_path: Optional[str] = None) -> MarginPositionLedger:
    global _LEDGER_SINGLETON
    if db_path is not None:
        return MarginPositionLedger(db_path=db_path)
    if _LEDGER_SINGLETON is not None:
        return _LEDGER_SINGLETON
    with _LEDGER_SINGLETON_LOCK:
        if _LEDGER_SINGLETON is None:
            _LEDGER_SINGLETON = MarginPositionLedger()
    return _LEDGER_SINGLETON
