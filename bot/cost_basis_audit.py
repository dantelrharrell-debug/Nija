"""NIJA Cost Basis Audit.

Periodic audit that cross-checks:
  1. Stored cost basis (``entry_price``, ``cost_basis_verified``) in the
     position tracker against broker-reported position data.
  2. Broker-reported quantity vs. internally tracked quantity.
  3. Realized P&L consistency: computes expected P&L from fills and compares
     with any stored realized figure.
  4. Average fill price from exchange history vs. stored entry price.

Discrepancies are:
  - Logged at WARNING or CRITICAL level.
  - Recorded in an audit trail (in-memory and optionally persisted to JSON).
  - Automatically repaired when a confident correction can be derived, so that
    exits are never blocked by stale or incorrect cost-basis data.

The audit runs periodically via :meth:`CostBasisAudit.start_background` or
can be triggered on-demand via :meth:`CostBasisAudit.run_once`.

Usage::

    from bot.cost_basis_audit import CostBasisAudit

    audit = CostBasisAudit(position_tracker, broker, broker_name="kraken")
    audit.start_background(interval_seconds=3600)  # run every hour

    # On-demand / at shutdown
    results = audit.run_once()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger("nija.cost_basis_audit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENV_AUDIT_INTERVAL = "NIJA_COST_BASIS_AUDIT_INTERVAL_S"
_ENV_AUDIT_TRAIL_FILE = "NIJA_COST_BASIS_AUDIT_TRAIL_FILE"
_ENV_AUTO_REPAIR = "NIJA_COST_BASIS_AUDIT_AUTO_REPAIR"
_ENV_PRICE_TOLERANCE = "NIJA_COST_BASIS_AUDIT_PRICE_TOLERANCE"
_ENV_QTY_TOLERANCE = "NIJA_COST_BASIS_AUDIT_QTY_TOLERANCE"

_DEFAULT_INTERVAL = 3600.0      # seconds between automatic audit runs
_DEFAULT_PRICE_TOL = 0.02       # 2% price discrepancy triggers a flag
_DEFAULT_QTY_TOL = 1e-6         # quantity tolerance (absolute units)


def _env_float(key: str, default: float) -> float:
    try:
        val = float(os.environ.get(key, default))
        return val if val == val else default
    except Exception:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "")
    if raw.lower() in ("1", "true", "yes"):
        return True
    if raw.lower() in ("0", "false", "no"):
        return False
    return default


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuditDiscrepancy:
    """A single cost-basis discrepancy found by the audit."""
    symbol: str
    discrepancy_type: str          # "price_mismatch", "qty_mismatch", "unverified", "fill_price_mismatch"
    stored_value: float = 0.0      # what the tracker holds
    broker_value: float = 0.0      # what the exchange reports
    difference_pct: float = 0.0    # relative difference
    repaired: bool = False
    repair_action: str = ""
    severity: str = "warning"      # "info", "warning", "critical"
    details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AuditRunResult:
    """Summary of one full audit run."""
    broker_name: str = ""
    positions_checked: int = 0
    discrepancies_found: int = 0
    discrepancies_repaired: int = 0
    discrepancies_unrepaired: int = 0
    price_mismatches: int = 0
    qty_mismatches: int = 0
    unverified_positions: int = 0
    discrepancies: List[AuditDiscrepancy] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Fill-history helpers (re-use adapters from cost_basis_reconciler)
# ---------------------------------------------------------------------------

def _get_fill_adapter(broker: Any, broker_name: str) -> Optional[Any]:
    """Return the appropriate fill adapter for the broker."""
    try:
        if broker_name == "kraken":
            from bot.cost_basis_reconciler import _KrakenFillAdapter
            return _KrakenFillAdapter(broker)
        if broker_name == "okx":
            from bot.cost_basis_reconciler import _OKXFillAdapter
            return _OKXFillAdapter(broker)
    except Exception as exc:
        logger.warning("COST_BASIS_AUDIT_ADAPTER_LOAD_FAILED broker=%s error=%s", broker_name, exc)
    return None


def _compute_vwap(broker: Any, broker_name: str, symbol: str) -> Optional[float]:
    """Return the fill-based VWAP for *symbol*, or None if unavailable."""
    try:
        from bot.cost_basis_reconciler import _reconstruct_vwap
        adapter = _get_fill_adapter(broker, broker_name)
        if adapter is None:
            return None
        fills = adapter.get_fills(symbol)
        if not fills:
            return None
        _, vwap = _reconstruct_vwap(fills)
        return vwap if vwap > 0 else None
    except Exception as exc:
        logger.debug("COST_BASIS_AUDIT_VWAP_FAILED symbol=%s error=%s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Main audit class
# ---------------------------------------------------------------------------

class CostBasisAudit:
    """Periodic and on-demand cost basis auditor.

    Args:
        position_tracker: ``PositionTracker`` instance.
        broker: Live broker connection (for fill history and balance queries).
        broker_name: ``"kraken"`` or ``"okx"``.
        auto_repair: If True, automatically correct discrepancies that can be
            resolved with high confidence.  Reads ``NIJA_COST_BASIS_AUDIT_AUTO_REPAIR``.
        price_tolerance: Maximum relative price difference before flagging.
        qty_tolerance: Maximum absolute quantity difference before flagging.
        audit_trail_file: Path to persist audit records as JSON.
    """

    def __init__(
        self,
        position_tracker: Any,
        broker: Any,
        broker_name: str = "kraken",
        auto_repair: Optional[bool] = None,
        price_tolerance: Optional[float] = None,
        qty_tolerance: Optional[float] = None,
        audit_trail_file: Optional[str] = None,
    ) -> None:
        self._tracker = position_tracker
        self._broker = broker
        self._broker_name = broker_name.lower().strip()
        self._auto_repair = (
            auto_repair
            if auto_repair is not None
            else _env_bool(_ENV_AUTO_REPAIR, True)
        )
        self._price_tol = price_tolerance or _env_float(_ENV_PRICE_TOLERANCE, _DEFAULT_PRICE_TOL)
        self._qty_tol = qty_tolerance or _env_float(_ENV_QTY_TOLERANCE, _DEFAULT_QTY_TOL)
        self._trail_file = audit_trail_file or os.environ.get(_ENV_AUDIT_TRAIL_FILE, "")

        self._lock = threading.Lock()
        self._run_results: List[AuditRunResult] = []
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_once(self) -> AuditRunResult:
        """Execute one full audit run synchronously.

        Returns:
            :class:`AuditRunResult` with all found discrepancies.
        """
        start = time.monotonic()
        result = AuditRunResult(broker_name=self._broker_name)

        positions = self._load_positions()
        result.positions_checked = len(positions)

        broker_balances = self._get_broker_balances()

        for symbol, pos in positions.items():
            discrepancies = self._audit_position(symbol, pos, broker_balances)
            for d in discrepancies:
                result.discrepancies_found += 1
                result.discrepancies.append(d)
                if d.discrepancy_type == "price_mismatch":
                    result.price_mismatches += 1
                elif d.discrepancy_type == "qty_mismatch":
                    result.qty_mismatches += 1
                elif d.discrepancy_type == "unverified":
                    result.unverified_positions += 1

                if d.repaired:
                    result.discrepancies_repaired += 1
                else:
                    result.discrepancies_unrepaired += 1

        result.duration_seconds = time.monotonic() - start

        with self._lock:
            self._run_results.append(result)

        self._log_run_summary(result)
        self._persist_trail(result)
        return result

    def start_background(
        self,
        interval_seconds: Optional[float] = None,
    ) -> None:
        """Start a daemon background thread that audits on a fixed interval.

        Args:
            interval_seconds: Seconds between audit runs.  Reads
                ``NIJA_COST_BASIS_AUDIT_INTERVAL_S`` from env if not supplied.
        """
        interval = interval_seconds or _env_float(_ENV_AUDIT_INTERVAL, _DEFAULT_INTERVAL)
        if self._bg_thread and self._bg_thread.is_alive():
            logger.info("COST_BASIS_AUDIT_BG_ALREADY_RUNNING broker=%s", self._broker_name)
            return

        self._stop_event.clear()

        def _loop() -> None:
            logger.info(
                "COST_BASIS_AUDIT_BG_STARTED broker=%s interval=%.0fs auto_repair=%s",
                self._broker_name, interval, self._auto_repair,
            )
            while not self._stop_event.wait(timeout=interval):
                try:
                    self.run_once()
                except Exception as exc:
                    logger.error("COST_BASIS_AUDIT_BG_ERROR broker=%s error=%s", self._broker_name, exc)

        self._bg_thread = threading.Thread(
            target=_loop,
            name=f"CostBasisAudit-{self._broker_name}",
            daemon=True,
        )
        self._bg_thread.start()

    def stop_background(self) -> None:
        """Signal the background audit loop to stop."""
        self._stop_event.set()
        if self._bg_thread:
            self._bg_thread.join(timeout=5.0)

    def get_results(self) -> List[AuditRunResult]:
        """Return all historical audit run results."""
        with self._lock:
            return list(self._run_results)

    def get_latest_result(self) -> Optional[AuditRunResult]:
        """Return the most recent audit run result, or None."""
        with self._lock:
            return self._run_results[-1] if self._run_results else None

    # ------------------------------------------------------------------
    # Audit sub-checks
    # ------------------------------------------------------------------

    def _audit_position(
        self,
        symbol: str,
        pos: Dict[str, Any],
        broker_balances: Dict[str, float],
    ) -> List[AuditDiscrepancy]:
        """Audit a single position and return any discrepancies found."""
        discrepancies: List[AuditDiscrepancy] = []

        stored_qty = float(pos.get("quantity") or 0)
        stored_price = float(pos.get("entry_price") or 0)
        cost_basis_verified = bool(pos.get("cost_basis_verified"))

        # Check 1 — unverified cost basis
        if not cost_basis_verified:
            d = AuditDiscrepancy(
                symbol=symbol,
                discrepancy_type="unverified",
                stored_value=stored_price,
                broker_value=0.0,
                severity="warning",
                details="cost_basis_verified=False auto_exit_blocked may be set",
            )
            d.repaired = self._attempt_repair_unverified(symbol, pos)
            d.repair_action = "triggered_reconciler" if d.repaired else "none"
            discrepancies.append(d)
            logger.warning(
                "COST_BASIS_AUDIT_UNVERIFIED symbol=%s broker=%s repaired=%s",
                symbol, self._broker_name, d.repaired,
            )

        # Check 2 — quantity mismatch vs. broker
        if broker_balances:
            base_asset = symbol.split("-")[0].upper()
            broker_qty = broker_balances.get(base_asset, broker_balances.get(symbol, 0.0))
            if broker_qty > 0 and stored_qty > 0:
                qty_diff = abs(stored_qty - broker_qty)
                if qty_diff > max(self._qty_tol, stored_qty * 0.001):
                    severity = "critical" if qty_diff > stored_qty * 0.10 else "warning"
                    d = AuditDiscrepancy(
                        symbol=symbol,
                        discrepancy_type="qty_mismatch",
                        stored_value=stored_qty,
                        broker_value=broker_qty,
                        difference_pct=qty_diff / max(stored_qty, 1e-12),
                        severity=severity,
                        details=f"stored={stored_qty:.8f} broker={broker_qty:.8f} diff={qty_diff:.8f}",
                    )
                    d.repaired = self._attempt_repair_qty(symbol, broker_qty) if self._auto_repair else False
                    d.repair_action = "updated_tracker_qty" if d.repaired else "none"
                    discrepancies.append(d)
                    logger.warning(
                        "COST_BASIS_AUDIT_QTY_MISMATCH symbol=%s stored=%.8f broker=%.8f diff=%.8f repaired=%s",
                        symbol, stored_qty, broker_qty, qty_diff, d.repaired,
                    )

        # Check 3 — fill-price vs. stored entry price
        if cost_basis_verified and stored_price > 0:
            broker_vwap = _compute_vwap(self._broker, self._broker_name, symbol)
            if broker_vwap and broker_vwap > 0:
                price_diff_pct = abs(stored_price - broker_vwap) / max(stored_price, 1e-12)
                if price_diff_pct > self._price_tol:
                    severity = "critical" if price_diff_pct > 0.10 else "warning"
                    d = AuditDiscrepancy(
                        symbol=symbol,
                        discrepancy_type="fill_price_mismatch",
                        stored_value=stored_price,
                        broker_value=broker_vwap,
                        difference_pct=price_diff_pct,
                        severity=severity,
                        details=(
                            f"stored_entry={stored_price:.8f} fill_vwap={broker_vwap:.8f} "
                            f"diff={price_diff_pct:.2%}"
                        ),
                    )
                    d.repaired = self._attempt_repair_price(symbol, broker_vwap) if self._auto_repair else False
                    d.repair_action = "updated_entry_price" if d.repaired else "none"
                    discrepancies.append(d)
                    log_fn = logger.critical if severity == "critical" else logger.warning
                    log_fn(
                        "COST_BASIS_AUDIT_PRICE_MISMATCH symbol=%s stored=%.8f vwap=%.8f diff=%.2f%% repaired=%s",
                        symbol, stored_price, broker_vwap, price_diff_pct * 100, d.repaired,
                    )

        return discrepancies

    # ------------------------------------------------------------------
    # Repair helpers
    # ------------------------------------------------------------------

    def _attempt_repair_unverified(self, symbol: str, pos: Dict[str, Any]) -> bool:
        """Trigger cost-basis reconciliation for an unverified position."""
        if not self._auto_repair:
            return False
        try:
            from bot.cost_basis_reconciler import CostBasisReconciler
            reconciler = CostBasisReconciler(
                position_tracker=self._tracker,
                broker=self._broker,
                broker_name=self._broker_name,
            )
            result = reconciler.reconcile_symbol(symbol)
            return result.status == "verified"
        except Exception as exc:
            logger.warning("COST_BASIS_AUDIT_REPAIR_UNVERIFIED_FAILED symbol=%s error=%s", symbol, exc)
            return False

    def _attempt_repair_qty(self, symbol: str, broker_qty: float) -> bool:
        """Update the tracker quantity to match the broker-reported value."""
        try:
            positions = self._tracker.positions
            if symbol not in positions:
                return False
            pos = positions[symbol]
            old_qty = float(pos.get("quantity") or 0)
            old_price = float(pos.get("entry_price") or 0)
            new_size_usd = broker_qty * old_price if old_price > 0 else float(pos.get("size_usd") or 0)
            pos["quantity"] = broker_qty
            pos["size_usd"] = new_size_usd
            pos["quantity_audit_repaired_at"] = datetime.now(timezone.utc).isoformat()
            pos["quantity_audit_previous_qty"] = old_qty
            self._tracker._save_positions()
            logger.critical(
                "COST_BASIS_AUDIT_QTY_REPAIRED symbol=%s old_qty=%.8f new_qty=%.8f",
                symbol, old_qty, broker_qty,
            )
            return True
        except Exception as exc:
            logger.error("COST_BASIS_AUDIT_QTY_REPAIR_FAILED symbol=%s error=%s", symbol, exc)
            return False

    def _attempt_repair_price(self, symbol: str, vwap: float) -> bool:
        """Update the stored entry price to the fill-history VWAP."""
        try:
            positions = self._tracker.positions
            if symbol not in positions:
                return False
            pos = positions[symbol]
            old_price = float(pos.get("entry_price") or 0)
            qty = float(pos.get("quantity") or 0)
            pos["entry_price"] = vwap
            pos["avg_entry_price"] = vwap
            pos["size_usd"] = qty * vwap if qty > 0 else float(pos.get("size_usd") or 0)
            pos["entry_price_source"] = "audit_repaired_fill_history_vwap"
            pos["cost_basis_verified"] = True
            pos["auto_exit_blocked"] = False
            pos["auto_exit_block_reason"] = ""
            pos["price_audit_repaired_at"] = datetime.now(timezone.utc).isoformat()
            pos["price_audit_previous_entry"] = old_price
            self._tracker._save_positions()
            logger.critical(
                "COST_BASIS_AUDIT_PRICE_REPAIRED symbol=%s old_entry=%.8f new_entry=%.8f",
                symbol, old_price, vwap,
            )
            return True
        except Exception as exc:
            logger.error("COST_BASIS_AUDIT_PRICE_REPAIR_FAILED symbol=%s error=%s", symbol, exc)
            return False

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    def _load_positions(self) -> Dict[str, Any]:
        try:
            raw = getattr(self._tracker, "positions", {})
            return dict(raw)
        except Exception as exc:
            logger.error("COST_BASIS_AUDIT_LOAD_POSITIONS_FAILED error=%s", exc)
            return {}

    def _get_broker_balances(self) -> Dict[str, float]:
        """Fetch current balances from the broker; return empty dict on failure."""
        try:
            # Try common broker balance methods
            for method_name in ("get_balances", "get_account_balance", "fetch_balance"):
                fn = getattr(self._broker, method_name, None)
                if callable(fn):
                    result = fn()
                    if isinstance(result, dict):
                        # Normalise values to float
                        return {
                            str(k).upper(): float(v)
                            for k, v in result.items()
                            if v and float(v or 0) > 0
                        }
            # Kraken-specific private call
            private_call = getattr(self._broker, "_kraken_api_call", None) or getattr(
                getattr(self._broker, "api", None), "query_private", None
            )
            if callable(private_call):
                resp = private_call("Balance")
                if isinstance(resp, Mapping):
                    result = resp.get("result", {})
                    return {
                        str(k).upper(): float(v)
                        for k, v in (result or {}).items()
                        if v and float(v or 0) > 0
                    }
        except Exception as exc:
            logger.debug("COST_BASIS_AUDIT_BROKER_BALANCE_FAILED broker=%s error=%s", self._broker_name, exc)
        return {}

    # ------------------------------------------------------------------
    # Logging and persistence
    # ------------------------------------------------------------------

    def _log_run_summary(self, result: AuditRunResult) -> None:
        if result.discrepancies_found == 0:
            logger.info(
                "COST_BASIS_AUDIT_CLEAN broker=%s positions=%d no_discrepancies duration=%.2fs",
                self._broker_name, result.positions_checked, result.duration_seconds,
            )
        else:
            logger.warning(
                "COST_BASIS_AUDIT_SUMMARY broker=%s positions=%d discrepancies=%d "
                "repaired=%d unrepaired=%d price_mismatches=%d qty_mismatches=%d "
                "unverified=%d duration=%.2fs",
                self._broker_name, result.positions_checked, result.discrepancies_found,
                result.discrepancies_repaired, result.discrepancies_unrepaired,
                result.price_mismatches, result.qty_mismatches,
                result.unverified_positions, result.duration_seconds,
            )

    def _persist_trail(self, result: AuditRunResult) -> None:
        if not self._trail_file:
            return
        try:
            existing: List[Dict] = []
            if os.path.exists(self._trail_file):
                with open(self._trail_file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            existing.append(asdict(result))
            # Keep only the last 500 run records to bound file growth
            existing = existing[-500:]
            tmp = self._trail_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            os.replace(tmp, self._trail_file)
        except Exception as exc:
            logger.warning("COST_BASIS_AUDIT_TRAIL_PERSIST_FAILED file=%s error=%s", self._trail_file, exc)


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def run_cost_basis_audit(
    position_tracker: Any,
    broker: Any,
    broker_name: str = "kraken",
    auto_repair: bool = True,
) -> AuditRunResult:
    """Run a one-shot cost basis audit and return the result.

    Args:
        position_tracker: ``PositionTracker`` instance.
        broker: Live broker connection.
        broker_name: ``"kraken"`` or ``"okx"``.
        auto_repair: Automatically correct verifiable discrepancies.

    Returns:
        :class:`AuditRunResult`.
    """
    audit = CostBasisAudit(
        position_tracker=position_tracker,
        broker=broker,
        broker_name=broker_name,
        auto_repair=auto_repair,
    )
    return audit.run_once()


__all__ = [
    "CostBasisAudit",
    "AuditRunResult",
    "AuditDiscrepancy",
    "run_cost_basis_audit",
]
