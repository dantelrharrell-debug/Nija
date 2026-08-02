"""NIJA Cost Basis Reconciler.

Unified cost basis reconciliation for positions held on Kraken and OKX.

Recovery pipeline (attempted in order):
  1. Check if position already carries ``cost_basis_verified=True`` — skip.
  2. Fetch paginated fill/trade history from the exchange.
  3. Reconstruct the weighted-average entry price (VWAP) from fills.
  4. Persist the verified basis to the PositionTracker and clear the
     ``auto_exit_blocked`` flag so exits can proceed immediately.
  5. If history is insufficient or the exchange API is unavailable, create an
     explicit **adopted-position** record that captures:
       - adoption_timestamp
       - adoption_price (current market price at adoption time)
       - adoption_source (``"market_price"`` or ``"user_supplied"``)
       - auto_manage_adopted (configurable policy — see ADOPTED_AUTO_MANAGE_POLICY)

Adoption policy is governed by the environment variable
``NIJA_ADOPTED_POSITION_POLICY``:
  - ``"block"``   (default) — adopted positions remain auto-exit-blocked.
  - ``"allow"``   — adopted positions are treated the same as verified ones.
  - ``"alert"``   — adopted positions generate a warning log on every exit
                    attempt but are not blocked.

Usage::

    from bot.cost_basis_reconciler import CostBasisReconciler

    reconciler = CostBasisReconciler(position_tracker, broker, broker_name="kraken")
    await reconciler.run()   # or reconciler.run_sync() for synchronous callers
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

logger = logging.getLogger("nija.cost_basis_reconciler")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENV_ADOPTED_POLICY = "NIJA_ADOPTED_POSITION_POLICY"
_ENV_DUST_THRESHOLD = "NIJA_DUST_THRESHOLD_USD"
_ENV_KRAKEN_PAGE_SIZE = "NIJA_KRAKEN_TRADES_HISTORY_PAGE_SIZE"
_ENV_KRAKEN_MAX_PAGES = "NIJA_KRAKEN_TRADES_HISTORY_MAX_PAGES"

_ADOPTED_POLICY_BLOCK = "block"
_ADOPTED_POLICY_ALLOW = "allow"
_ADOPTED_POLICY_ALERT = "alert"
_VALID_POLICIES = {_ADOPTED_POLICY_BLOCK, _ADOPTED_POLICY_ALLOW, _ADOPTED_POLICY_ALERT}

_VERIFIED_ENTRY_SOURCE = "reconciled_fill_history_vwap"
_ADOPTED_ENTRY_SOURCE = "adopted_position"


def _env_float(key: str, default: float) -> float:
    try:
        val = float(os.environ.get(key, default))
        return val if val == val and val > 0 else default  # guard NaN
    except Exception:
        return default


def _adopted_policy() -> str:
    raw = os.environ.get(_ENV_ADOPTED_POLICY, _ADOPTED_POLICY_BLOCK).strip().lower()
    return raw if raw in _VALID_POLICIES else _ADOPTED_POLICY_BLOCK


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FillRecord:
    """A single fill (executed trade leg)."""
    timestamp: float           # unix epoch seconds
    side: str                  # "buy" or "sell"
    quantity: float            # base units
    price: float               # quote per base
    fee: float = 0.0           # fee in quote units
    order_id: str = ""
    trade_id: str = ""


@dataclass
class ReconciliationResult:
    """Outcome for one position after reconciliation."""
    symbol: str
    status: str = "unknown"    # "verified", "adopted", "skipped", "error"
    entry_price: float = 0.0
    quantity: float = 0.0
    fills_used: int = 0
    adoption_policy: str = ""
    auto_exit_blocked: bool = True
    details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Fill history adapters (exchange-specific)
# ---------------------------------------------------------------------------

class _KrakenFillAdapter:
    """Fetches and normalises fill history from Kraken TradesHistory."""

    KRAKEN_BASE_ALIASES: Dict[str, str] = {
        "XXBT": "BTC", "XBT": "BTC",
        "XETH": "ETH",
        "XXRP": "XRP",
        "XXLM": "XLM",
        "XLTC": "LTC",
        "XXMR": "XMR",
        "XETC": "ETC",
        "ZUSD": "USD",
        "ZEUR": "EUR",
    }

    def __init__(self, broker: Any) -> None:
        self._broker = broker

    def _private_call(self, params: Dict[str, Any]) -> Mapping[str, Any]:
        caller = getattr(self._broker, "_kraken_api_call", None)
        if callable(caller):
            result = caller("TradesHistory", params)
        else:
            api = getattr(self._broker, "api", None) or getattr(self._broker, "kraken_api", None)
            query_private = getattr(api, "query_private", None)
            if not callable(query_private):
                return {}
            result = query_private("TradesHistory", params)
        return result if isinstance(result, Mapping) else {}

    @classmethod
    def _normalise_base(cls, raw: str) -> str:
        text = raw.upper().strip()
        for quote in ("ZUSD", "USD", "USDT", "USDC", "ZEUR", "EUR"):
            if text.endswith(quote) and len(text) > len(quote):
                text = text[: -len(quote)]
                break
        return cls.KRAKEN_BASE_ALIASES.get(text, text)

    def get_fills(self, symbol: str) -> List[FillRecord]:
        """Return all fills for *symbol* in chronological order."""
        page_size = int(_env_float(_ENV_KRAKEN_PAGE_SIZE, 50))
        max_pages = int(_env_float(_ENV_KRAKEN_MAX_PAGES, 40))

        target_base = symbol.split("-", 1)[0].upper()
        # normalise: BTC→XBT (Kraken native)
        if target_base == "BTC":
            target_base = "XBT"

        all_trades: Dict[str, Any] = {}
        expected: Optional[int] = None

        for page in range(max_pages):
            offset = page * page_size
            payload = self._private_call({"type": "all", "trades": True, "ofs": offset})
            if payload.get("error"):
                logger.warning(
                    "KRAKEN_FILL_HISTORY_PAGE_FAILED symbol=%s offset=%d error=%s",
                    symbol, offset, payload.get("error"),
                )
                break
            result = payload.get("result")
            if not isinstance(result, Mapping):
                break
            trades = result.get("trades")
            if not isinstance(trades, Mapping) or not trades:
                break
            all_trades.update(trades)
            if expected is None:
                expected = int(float(result.get("count", len(trades))))
            if len(all_trades) >= expected or len(trades) < page_size:
                break

        fills: List[FillRecord] = []
        for row in all_trades.values():
            if not isinstance(row, Mapping):
                continue
            raw_base = self._normalise_base(str(row.get("pair") or ""))
            if raw_base != target_base:
                continue
            try:
                side = str(row.get("type") or "").strip().lower()
                qty = abs(float(row.get("vol", 0) or 0))
                price = float(row.get("price", 0) or 0)
                fee = abs(float(row.get("fee", 0) or 0))
                ts = float(row.get("time", 0) or 0)
                if qty > 0 and price > 0 and side in ("buy", "sell"):
                    fills.append(FillRecord(
                        timestamp=ts,
                        side=side,
                        quantity=qty,
                        price=price,
                        fee=fee,
                        trade_id=str(row.get("postxid") or row.get("txid") or ""),
                    ))
            except (TypeError, ValueError):
                continue

        fills.sort(key=lambda f: f.timestamp)
        logger.info(
            "KRAKEN_FILL_HISTORY_LOADED symbol=%s total_system_trades=%d matching_fills=%d",
            symbol, len(all_trades), len(fills),
        )
        return fills


class _OKXFillAdapter:
    """Fetches and normalises fill history from OKX /trade/fills."""

    def __init__(self, broker: Any) -> None:
        self._broker = broker

    def _okx_inst_id(self, symbol: str) -> str:
        """Convert standard symbol (BTC-USD) to OKX instId (BTC-USDT)."""
        return symbol.replace("-USD", "-USDT") if symbol.endswith("-USD") else symbol

    def get_fills(self, symbol: str) -> List[FillRecord]:
        """Return all available fills for *symbol* from OKX trade history."""
        trade_api = getattr(self._broker, "trade_api", None)
        if trade_api is None:
            # Some OKX broker wrappers expose get_fills directly
            get_fills_fn = getattr(self._broker, "get_fills", None)
            if not callable(get_fills_fn):
                logger.warning("OKX_FILL_ADAPTER_UNAVAILABLE symbol=%s no_trade_api", symbol)
                return []
            trade_api = self._broker

        inst_id = self._okx_inst_id(symbol)
        fills: List[FillRecord] = []

        try:
            result = trade_api.get_fills(instId=inst_id, limit="100")
            if not (result and result.get("code") == "0"):
                logger.warning(
                    "OKX_FILL_HISTORY_FAILED symbol=%s inst_id=%s code=%s",
                    symbol, inst_id, result.get("code") if result else "no_response",
                )
                return []
            for fill in result.get("data", []):
                if not isinstance(fill, dict):
                    continue
                try:
                    side = str(fill.get("side") or "").strip().lower()
                    qty = float(fill.get("fillSz", 0) or 0)
                    price = float(fill.get("fillPx", 0) or 0)
                    fee = abs(float(fill.get("fee", 0) or 0))
                    ts_ms = float(fill.get("ts", 0) or 0)
                    ts = ts_ms / 1000.0 if ts_ms > 1e10 else ts_ms
                    if qty > 0 and price > 0 and side in ("buy", "sell"):
                        fills.append(FillRecord(
                            timestamp=ts,
                            side=side,
                            quantity=qty,
                            price=price,
                            fee=fee,
                            trade_id=str(fill.get("tradeId") or ""),
                            order_id=str(fill.get("ordId") or ""),
                        ))
                except (TypeError, ValueError):
                    continue
        except Exception as exc:
            logger.warning("OKX_FILL_HISTORY_EXCEPTION symbol=%s error=%s", symbol, exc)
            return []

        fills.sort(key=lambda f: f.timestamp)
        logger.info("OKX_FILL_HISTORY_LOADED symbol=%s fills=%d", symbol, len(fills))
        return fills


# ---------------------------------------------------------------------------
# VWAP reconstruction
# ---------------------------------------------------------------------------

def _reconstruct_vwap(fills: Iterable[FillRecord]) -> Tuple[float, float]:
    """Compute remaining quantity and VWAP entry price from an ordered fill list.

    Uses a FIFO/running-inventory approach: buys add to position cost; sells
    reduce it proportionally.

    Returns:
        (remaining_quantity, weighted_avg_price)  — (0, 0) if no position remains.
    """
    qty_held = 0.0
    cost_held = 0.0  # total cost including fees

    for fill in fills:
        if fill.side == "buy":
            cost = fill.quantity * fill.price + fill.fee
            qty_held += fill.quantity
            cost_held += cost
        elif fill.side == "sell" and qty_held > 1e-12:
            avg = cost_held / qty_held
            removed = min(fill.quantity, qty_held)
            qty_held -= removed
            cost_held = max(0.0, cost_held - removed * avg)

    if qty_held < 1e-12 or cost_held <= 0:
        return 0.0, 0.0
    return qty_held, cost_held / qty_held


# ---------------------------------------------------------------------------
# Main reconciler
# ---------------------------------------------------------------------------

class CostBasisReconciler:
    """Reconcile cost basis for a single broker's positions.

    Args:
        position_tracker: A ``PositionTracker`` instance (or compatible dict
            store with ``positions`` attribute and ``_save_positions`` method).
        broker: Live broker instance used to fetch fills.
        broker_name: One of ``"kraken"`` or ``"okx"``.
        dust_threshold_usd: Positions below this USD value are skipped (dust).
    """

    def __init__(
        self,
        position_tracker: Any,
        broker: Any,
        broker_name: str = "kraken",
        dust_threshold_usd: Optional[float] = None,
    ) -> None:
        self._tracker = position_tracker
        self._broker = broker
        self._broker_name = broker_name.lower().strip()
        self._dust_usd = (
            dust_threshold_usd
            if dust_threshold_usd is not None
            else _env_float(_ENV_DUST_THRESHOLD, 1.0)
        )
        self._lock = threading.Lock()
        self._results: List[ReconciliationResult] = []

        if self._broker_name == "kraken":
            self._adapter: Any = _KrakenFillAdapter(broker)
        elif self._broker_name == "okx":
            self._adapter = _OKXFillAdapter(broker)
        else:
            self._adapter = None
            logger.warning(
                "COST_BASIS_RECONCILER_NO_ADAPTER broker=%s — only 'kraken' and 'okx' are supported",
                self._broker_name,
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_sync(self) -> List[ReconciliationResult]:
        """Synchronously reconcile all unverified positions.

        Returns:
            List of :class:`ReconciliationResult` for each processed position.
        """
        if self._adapter is None:
            logger.error("COST_BASIS_RECONCILER_SKIPPED no adapter for broker=%s", self._broker_name)
            return []

        positions = self._get_unverified_positions()
        if not positions:
            logger.info("COST_BASIS_RECONCILER_NOTHING_TO_DO broker=%s all_verified_or_empty", self._broker_name)
            return []

        logger.info(
            "COST_BASIS_RECONCILER_START broker=%s unverified_positions=%d",
            self._broker_name, len(positions),
        )

        results: List[ReconciliationResult] = []
        for symbol, position in positions.items():
            result = self._reconcile_one(symbol, position)
            results.append(result)
            logger.info(
                "COST_BASIS_RECONCILER_RESULT broker=%s symbol=%s status=%s "
                "entry_price=%.8f fills_used=%d auto_exit_blocked=%s details=%s",
                self._broker_name, symbol, result.status, result.entry_price,
                result.fills_used, result.auto_exit_blocked, result.details,
            )

        with self._lock:
            self._results.extend(results)

        verified = sum(1 for r in results if r.status == "verified")
        adopted = sum(1 for r in results if r.status == "adopted")
        errors = sum(1 for r in results if r.status == "error")
        logger.info(
            "COST_BASIS_RECONCILER_COMPLETE broker=%s total=%d verified=%d adopted=%d errors=%d",
            self._broker_name, len(results), verified, adopted, errors,
        )
        return results

    def get_results(self) -> List[ReconciliationResult]:
        """Return all reconciliation results from previous runs."""
        with self._lock:
            return list(self._results)

    def reconcile_symbol(self, symbol: str) -> ReconciliationResult:
        """Force reconciliation of a single symbol regardless of verified flag.

        Useful for manual repair or periodic re-checks.
        """
        positions = self._tracker.positions if hasattr(self._tracker, "positions") else {}
        position = dict(positions.get(symbol, {}))
        result = self._reconcile_one(symbol, position)
        with self._lock:
            self._results.append(result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_unverified_positions(self) -> Dict[str, Dict]:
        """Return positions that need reconciliation (not yet verified)."""
        all_positions: Dict[str, Dict] = {}
        try:
            raw = self._tracker.positions if hasattr(self._tracker, "positions") else {}
            all_positions = dict(raw)
        except Exception as exc:
            logger.error("COST_BASIS_RECONCILER_LOAD_FAILED error=%s", exc)
            return {}

        unverified: Dict[str, Dict] = {}
        for symbol, pos in all_positions.items():
            if not isinstance(pos, dict):
                continue
            if pos.get("cost_basis_verified") is True:
                logger.debug("COST_BASIS_RECONCILER_SKIP_VERIFIED symbol=%s", symbol)
                continue
            if pos.get("classification") == "DUST" or pos.get("exclude_from_reconciliation") is True:
                logger.info("COST_BASIS_RECONCILER_SKIP_DUST symbol=%s", symbol)
                continue
            if pos.get("position_adoption_timestamp"):
                logger.info("COST_BASIS_RECONCILER_SKIP_ADOPTED symbol=%s", symbol)
                continue
            unverified[symbol] = pos

        return unverified

    def _is_dust(self, symbol: str, position: Dict) -> bool:
        """Return True if the position is below the dust threshold."""
        try:
            from bot.dust_position_filter import DustPositionFilter
            current_price = float(position.get("last_broker_snapshot_price") or 0)
            qty = float(position.get("quantity") or 0)
            if current_price > 0 and qty > 0:
                return DustPositionFilter().is_dust(symbol, qty, current_price)
        except Exception:
            pass

        # Fallback using stored size_usd
        size_usd = float(position.get("size_usd") or 0)
        if size_usd > 0:
            return size_usd < self._dust_usd

        qty = float(position.get("quantity") or 0)
        return qty < 1e-6  # ultra-tiny quantity — safe to treat as dust

    def _reconcile_one(self, symbol: str, position: Dict) -> ReconciliationResult:
        """Attempt full reconciliation for a single position."""
        qty = float(position.get("quantity") or 0)
        if qty <= 0:
            return ReconciliationResult(
                symbol=symbol,
                status="skipped",
                details="zero_or_missing_quantity",
                auto_exit_blocked=False,
            )

        if self._is_dust(symbol, position):
            return ReconciliationResult(
                symbol=symbol,
                status="skipped",
                quantity=qty,
                details=f"dust_position_below_threshold_{self._dust_usd}_usd",
                auto_exit_blocked=False,
            )

        try:
            fills = self._adapter.get_fills(symbol)
        except Exception as exc:
            logger.error("COST_BASIS_RECONCILER_FILL_FETCH_ERROR symbol=%s error=%s", symbol, exc)
            return self._adopt_position(symbol, position, reason=f"fill_fetch_exception: {exc}")

        if not fills:
            _qty_from_orders, _vwap_from_orders, _orders_used = self._recover_vwap_from_historical_orders(symbol)
            if _vwap_from_orders > 0 and _qty_from_orders + max(1e-8, qty * 0.02) >= qty:
                self._persist_verified(symbol, _vwap_from_orders, qty, _orders_used)
                return ReconciliationResult(
                    symbol=symbol,
                    status="verified",
                    entry_price=_vwap_from_orders,
                    quantity=qty,
                    fills_used=_orders_used,
                    adoption_policy="",
                    auto_exit_blocked=False,
                    details=(
                        f"vwap={_vwap_from_orders:.8f} reconstructed_qty={_qty_from_orders:.8f} "
                        f"source=historical_orders orders={_orders_used} broker={self._broker_name}"
                    ),
                )
            return self._adopt_position(symbol, position, reason="no_fill_history_returned")

        reconstructed_qty, vwap = _reconstruct_vwap(fills)

        # Allow 2% tolerance for partial fills / rounding
        tolerance = max(1e-8, qty * 0.02)
        if vwap <= 0 or reconstructed_qty + tolerance < qty:
            logger.warning(
                "COST_BASIS_RECONCILER_INSUFFICIENT_HISTORY symbol=%s "
                "held_qty=%.8f history_qty=%.8f fills=%d",
                symbol, qty, reconstructed_qty, len(fills),
            )
            _qty_from_orders, _vwap_from_orders, _orders_used = self._recover_vwap_from_historical_orders(symbol)
            if _vwap_from_orders > 0 and _qty_from_orders + tolerance >= qty:
                self._persist_verified(symbol, _vwap_from_orders, qty, _orders_used)
                return ReconciliationResult(
                    symbol=symbol,
                    status="verified",
                    entry_price=_vwap_from_orders,
                    quantity=qty,
                    fills_used=_orders_used,
                    adoption_policy="",
                    auto_exit_blocked=False,
                    details=(
                        f"vwap={_vwap_from_orders:.8f} reconstructed_qty={_qty_from_orders:.8f} "
                        f"source=historical_orders orders={_orders_used} broker={self._broker_name}"
                    ),
                )
            return self._adopt_position(
                symbol, position,
                reason=(
                    f"history_qty={reconstructed_qty:.8f}_insufficient_for_held_qty={qty:.8f}"
                ),
            )

        # Verified — persist to tracker
        self._persist_verified(symbol, vwap, qty, len(fills))
        policy = _adopted_policy()
        return ReconciliationResult(
            symbol=symbol,
            status="verified",
            entry_price=vwap,
            quantity=qty,
            fills_used=len(fills),
            adoption_policy="",
            auto_exit_blocked=False,
            details=(
                f"vwap={vwap:.8f} reconstructed_qty={reconstructed_qty:.8f} "
                f"fills={len(fills)} broker={self._broker_name}"
            ),
        )

    def _persist_verified(self, symbol: str, vwap: float, qty: float, fills_used: int) -> None:
        """Write verified cost basis back to the position tracker."""
        try:
            positions = self._tracker.positions
            if symbol not in positions:
                logger.warning("COST_BASIS_RECONCILER_PERSIST_MISSING symbol=%s", symbol)
                return
            now = datetime.now(timezone.utc).isoformat()
            positions[symbol].update({
                "entry_price": vwap,
                "avg_entry_price": vwap,
                "cost_basis_verified": True,
                "auto_exit_blocked": False,
                "auto_exit_block_reason": "",
                "entry_price_source": _VERIFIED_ENTRY_SOURCE,
                "cost_basis_provenance": f"{self._broker_name}:fill_history_vwap",
                "cost_basis_fills_used": fills_used,
                "cost_basis_verified_at": now,
            })
            self._tracker._save_positions()
            logger.critical(
                "COST_BASIS_RECONCILER_VERIFIED_PERSISTED broker=%s symbol=%s "
                "vwap=%.8f qty=%.8f fills=%d",
                self._broker_name, symbol, vwap, qty, fills_used,
            )
        except Exception as exc:
            logger.error("COST_BASIS_RECONCILER_PERSIST_FAILED symbol=%s error=%s", symbol, exc)

    def _adopt_position(self, symbol: str, position: Dict, reason: str) -> ReconciliationResult:
        """Create an adopted-position record when history cannot be recovered."""
        policy = _adopted_policy()
        qty = float(position.get("quantity") or 0)

        # Adoption price: use the most recent market snapshot if available,
        # falling back to any stored entry mark.
        adoption_price = float(
            position.get("last_broker_snapshot_price")
            or position.get("entry_price")
            or 0
        )
        now = datetime.now(timezone.utc).isoformat()

        auto_blocked = policy == _ADOPTED_POLICY_BLOCK
        block_reason = (
            ""
            if policy == _ADOPTED_POLICY_ALLOW
            else (
                "adopted_position_policy=alert"
                if policy == _ADOPTED_POLICY_ALERT
                else "adopted_position_history_unrecoverable"
            )
        )

        try:
            positions = self._tracker.positions
            if symbol in positions:
                existing = positions[symbol]
                # Only record adoption once (don't overwrite a previous adoption)
                if existing.get("position_adoption_timestamp"):
                    logger.debug("COST_BASIS_RECONCILER_ADOPTION_ALREADY_RECORDED symbol=%s", symbol)
                else:
                    existing.update({
                        "position_adoption_timestamp": now,
                        "position_adoption_price": adoption_price,
                        "adoption_timestamp": now,
                        "adoption_price": adoption_price,
                        "adopted_position": True,
                        "position_adoption_source": "market_price",
                        "position_adoption_reason": reason,
                        "position_adoption_policy": policy,
                        "entry_price_source": _ADOPTED_ENTRY_SOURCE,
                        "cost_basis_verified": False,
                        "auto_exit_blocked": auto_blocked,
                        "auto_exit_block_reason": block_reason,
                        "auto_manage_adopted": policy in (_ADOPTED_POLICY_ALLOW, _ADOPTED_POLICY_ALERT),
                    })
                    self._tracker._save_positions()
                    logger.warning(
                        "COST_BASIS_RECONCILER_ADOPTED broker=%s symbol=%s qty=%.8f "
                        "adoption_price=%.8f policy=%s auto_exit_blocked=%s reason=%s",
                        self._broker_name, symbol, qty, adoption_price,
                        policy, auto_blocked, reason,
                    )
        except Exception as exc:
            logger.error("COST_BASIS_RECONCILER_ADOPTION_PERSIST_FAILED symbol=%s error=%s", symbol, exc)

        return ReconciliationResult(
            symbol=symbol,
            status="adopted",
            entry_price=adoption_price,
            quantity=qty,
            fills_used=0,
            adoption_policy=policy,
            auto_exit_blocked=auto_blocked,
            details=f"reason={reason} policy={policy}",
        )

    def _recover_vwap_from_historical_orders(self, symbol: str) -> Tuple[float, float, int]:
        """Fallback recovery pipeline using historical orders when fills are unavailable."""
        order_rows: List[Mapping[str, Any]] = []
        candidate_methods = ("get_orders", "get_order_history", "fetch_orders", "list_orders")
        for method_name in candidate_methods:
            method = getattr(self._broker, method_name, None)
            if not callable(method):
                continue
            try:
                try:
                    payload = method(symbol=symbol)
                except TypeError:
                    payload = method(symbol)
                if isinstance(payload, Mapping):
                    for key in ("orders", "data", "result"):
                        maybe = payload.get(key)
                        if isinstance(maybe, list):
                            order_rows.extend([row for row in maybe if isinstance(row, Mapping)])
                            break
                elif isinstance(payload, list):
                    order_rows.extend([row for row in payload if isinstance(row, Mapping)])
            except Exception as exc:
                logger.debug("COST_BASIS_RECONCILER_ORDER_HISTORY_ERROR symbol=%s method=%s error=%s", symbol, method_name, exc)
            if order_rows:
                break

        fills: List[FillRecord] = []
        for row in order_rows:
            try:
                side = str(row.get("side") or row.get("action") or "").strip().lower()
                status = str(row.get("status") or row.get("state") or "").strip().lower()
                if status and status not in {"closed", "filled", "done", "executed"}:
                    continue
                qty = float(
                    row.get("filled_size")
                    or row.get("filled_qty")
                    or row.get("size")
                    or row.get("quantity")
                    or 0.0
                )
                price = float(
                    row.get("average_price")
                    or row.get("avg_price")
                    or row.get("fill_price")
                    or row.get("price")
                    or 0.0
                )
                if qty > 0 and price > 0 and side in {"buy", "sell"}:
                    fills.append(
                        FillRecord(
                            timestamp=float(row.get("timestamp") or row.get("ts") or 0.0),
                            side=side,
                            quantity=qty,
                            price=price,
                            fee=float(row.get("fee") or 0.0),
                            order_id=str(row.get("id") or row.get("order_id") or ""),
                        )
                    )
            except Exception:
                continue
        fills.sort(key=lambda x: x.timestamp)
        if not fills:
            return 0.0, 0.0, 0
        qty_held, vwap = _reconstruct_vwap(fills)
        logger.info(
            "COST_BASIS_RECONCILER_ORDER_HISTORY_RECOVERY symbol=%s broker=%s orders=%d qty=%.8f vwap=%.8f",
            symbol,
            self._broker_name,
            len(fills),
            qty_held,
            vwap,
        )
        return qty_held, vwap, len(fills)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def reconcile_broker_positions(
    position_tracker: Any,
    broker: Any,
    broker_name: str = "kraken",
    dust_threshold_usd: Optional[float] = None,
) -> List[ReconciliationResult]:
    """Reconcile all unverified positions for *broker* and return results.

    This is the recommended entry point for startup reconciliation.

    Args:
        position_tracker: ``PositionTracker`` instance.
        broker: Live broker connection.
        broker_name: ``"kraken"`` or ``"okx"``.
        dust_threshold_usd: Override the dust-skip threshold (reads from env
            ``NIJA_DUST_THRESHOLD_USD`` if not provided).

    Returns:
        List of :class:`ReconciliationResult`.
    """
    reconciler = CostBasisReconciler(
        position_tracker=position_tracker,
        broker=broker,
        broker_name=broker_name,
        dust_threshold_usd=dust_threshold_usd,
    )
    return reconciler.run_sync()


def is_auto_manageable(position: Mapping[str, Any]) -> bool:
    """Return True if an adopted position may be auto-managed (exited/trailed).

    A position is auto-manageable when:
    - Its cost basis is verified, **or**
    - It has been adopted and the policy is ``"allow"`` or ``"alert"``.
    """
    if position.get("cost_basis_verified") is True:
        return True
    policy = str(position.get("position_adoption_policy") or "").strip().lower()
    if policy in (_ADOPTED_POLICY_ALLOW, _ADOPTED_POLICY_ALERT):
        return bool(position.get("auto_manage_adopted"))
    return False


__all__ = [
    "CostBasisReconciler",
    "ReconciliationResult",
    "FillRecord",
    "reconcile_broker_positions",
    "is_auto_manageable",
]
