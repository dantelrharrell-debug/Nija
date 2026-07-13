"""NIJA Position Tracker.

Persistent, thread-safe position storage with an explicit distinction between a
verified cost basis and a temporary adoption mark.  A current market price may be
used for visibility, but it is never represented as a real entry price and is
never persisted to EntryPriceStore as execution truth.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger("nija")

try:
    from bot.entry_price_store import get_entry_price_store
    ENTRY_PRICE_STORE_AVAILABLE = True
except Exception:
    ENTRY_PRICE_STORE_AVAILABLE = False

_VERIFIED_SOURCES = {
    "api", "execution", "trade_history", "closed_orders", "fills",
    "manual_verified", "reconstructed_verified_cost_basis",
}
_UNVERIFIED_SOURCE_TOKENS = {
    "estimated", "adoption", "override", "reconciliation_required", "unknown", "missing",
}


class PositionTracker:
    """Track position cost basis and quantities across process restarts."""

    def __init__(self, storage_file: str = "positions.json"):
        self.storage_file = os.path.abspath(storage_file)
        self.positions: Dict[str, Dict] = {}
        self.lock = Lock()
        self._load_positions()
        self._eps = get_entry_price_store() if ENTRY_PRICE_STORE_AVAILABLE else None
        logger.info("PositionTracker initialized: %d tracked positions", len(self.positions))

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            parsed = float(value or 0.0)
        except (TypeError, ValueError, OverflowError):
            return default
        return parsed if parsed == parsed else default

    @staticmethod
    def _source_verified(source: str, price: float) -> bool:
        text = str(source or "").strip().lower()
        if price <= 0:
            return False
        if text in _VERIFIED_SOURCES:
            return True
        if any(token in text for token in _UNVERIFIED_SOURCE_TOKENS):
            return False
        return False

    @classmethod
    def _existing_verified(cls, position: Optional[Dict]) -> bool:
        if not position:
            return False
        explicit = position.get("cost_basis_verified")
        if explicit is not None:
            return explicit is True
        price = cls._safe_float(position.get("entry_price"))
        source = str(position.get("entry_price_source") or position.get("position_source") or "")
        return cls._source_verified(source, price)

    def _load_positions(self) -> None:
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self.positions = data.get("positions", {}) if isinstance(data, dict) else {}
                logger.info("Loaded %d positions from %s", len(self.positions), self.storage_file)
            else:
                logger.info("No existing positions file found - starting fresh")
        except Exception as exc:
            logger.error("Error loading positions: %s", exc)
            self.positions = {}

    def _save_positions(self) -> None:
        try:
            parent = os.path.dirname(self.storage_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            payload = {"positions": self.positions, "last_updated": datetime.now().isoformat()}
            temp_file = self.storage_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(temp_file, self.storage_file)
        except Exception as exc:
            logger.error("Error saving positions: %s", exc)

    def _persist_entry_price(self, symbol: str, price: float, quantity: float, source: str) -> None:
        if not ENTRY_PRICE_STORE_AVAILABLE or price <= 0 or not self._source_verified(source, price):
            return
        try:
            get_entry_price_store().save(symbol, price, source=source, quantity=quantity)
        except Exception as exc:
            logger.debug("[PositionTracker] entry_price_store save failed for %s: %s", symbol, exc)

    def track_entry(
        self,
        symbol: str,
        entry_price: float,
        quantity: float,
        size_usd: float,
        strategy: str = "APEX_v7.1",
        position_source: str = "nija_strategy",
    ) -> bool:
        """Record an actual additive trade fill."""
        try:
            symbol = str(symbol or "").strip()
            entry_price = self._safe_float(entry_price)
            quantity = self._safe_float(quantity)
            size_usd = self._safe_float(size_usd)
            if not symbol or quantity <= 0:
                return False
            fill_verified = entry_price > 0
            now = datetime.now().isoformat()

            with self.lock:
                existing = self.positions.get(symbol)
                if existing:
                    old_qty = self._safe_float(existing.get("quantity"))
                    old_price = self._safe_float(existing.get("entry_price"))
                    old_size = self._safe_float(existing.get("size_usd"))
                    total_qty = old_qty + quantity
                    total_cost = (old_qty * old_price) + (quantity * entry_price)
                    avg_price = total_cost / total_qty if total_qty > 0 else entry_price
                    total_size = old_size + size_usd
                    verified = self._existing_verified(existing) and fill_verified
                    entry_source = "execution" if verified else "execution_price_missing_or_mixed"
                    self.positions[symbol] = {
                        "entry_price": avg_price,
                        "quantity": total_qty,
                        "size_usd": total_size,
                        "first_entry_time": existing.get("first_entry_time", now),
                        "last_entry_time": now,
                        "strategy": strategy,
                        "num_adds": int(existing.get("num_adds", 0) or 0) + 1,
                        "previous_profit_pct": self._safe_float(existing.get("previous_profit_pct")),
                        "position_source": existing.get("position_source", position_source),
                        "entry_price_source": entry_source,
                        "cost_basis_verified": verified,
                        "auto_exit_blocked": not verified,
                        "auto_exit_block_reason": "" if verified else "unverified_cost_basis",
                    }
                    logger.info("Updated position %s: avg_entry=$%.2f, qty=%.8f verified=%s", symbol, avg_price, total_qty, verified)
                else:
                    verified = fill_verified
                    entry_source = "execution" if verified else "execution_price_missing"
                    self.positions[symbol] = {
                        "entry_price": entry_price,
                        "quantity": quantity,
                        "size_usd": size_usd,
                        "first_entry_time": now,
                        "last_entry_time": now,
                        "strategy": strategy,
                        "num_adds": 0,
                        "previous_profit_pct": 0.0,
                        "position_source": position_source,
                        "entry_price_source": entry_source,
                        "cost_basis_verified": verified,
                        "auto_exit_blocked": not verified,
                        "auto_exit_block_reason": "" if verified else "unverified_cost_basis",
                    }
                    logger.info(
                        "Tracking new position %s: entry=$%.2f, qty=%.8f, source=%s verified=%s",
                        symbol, entry_price, quantity, position_source, verified,
                    )
                self._save_positions()
                final = self.positions[symbol]
                effective = self._safe_float(final.get("entry_price"))
                final_qty = self._safe_float(final.get("quantity"))
                final_source = str(final.get("entry_price_source") or "")
                final_verified = final.get("cost_basis_verified") is True

            if final_verified:
                self._persist_entry_price(symbol, effective, final_qty, final_source)
            return True
        except Exception as exc:
            logger.error("Error tracking entry for %s: %s", symbol, exc)
            return False

    def sync_position_snapshot(
        self,
        symbol: str,
        quantity: float,
        entry_price: float = 0.0,
        current_price: float = 0.0,
        size_usd: float = 0.0,
        strategy: str = "BROKER_SYNC",
        position_source: str = "broker_existing",
        entry_price_source: str = "override",
    ) -> bool:
        """Reconcile an exact broker snapshot without treating it as a new fill."""
        try:
            symbol = str(symbol or "").strip()
            quantity = self._safe_float(quantity)
            supplied_entry = self._safe_float(entry_price)
            current_price = self._safe_float(current_price)
            broker_value = self._safe_float(size_usd)
            if not symbol or quantity <= 0:
                return False

            with self.lock:
                existing = self.positions.get(symbol)
                old_qty = self._safe_float((existing or {}).get("quantity"))
                old_entry = self._safe_float((existing or {}).get("entry_price"))
                old_cost = self._safe_float((existing or {}).get("size_usd"))
                old_verified = self._existing_verified(existing)
                repaired_from_cost = False

                if supplied_entry > 0:
                    effective_entry = supplied_entry
                    effective_source = str(entry_price_source or "override")
                    verified = self._source_verified(effective_source, effective_entry)
                elif existing and old_cost > 0 and quantity > 0 and old_verified:
                    effective_entry = old_cost / quantity
                    effective_source = "reconstructed_verified_cost_basis"
                    verified = True
                    repaired_from_cost = True
                elif old_entry > 0 and old_verified:
                    effective_entry = old_entry
                    effective_source = str((existing or {}).get("entry_price_source") or "execution")
                    verified = True
                elif current_price > 0:
                    effective_entry = current_price
                    effective_source = "estimated_from_adoption_mark"
                    verified = False
                elif broker_value > 0:
                    effective_entry = broker_value / quantity
                    effective_source = "estimated_from_broker_market_value"
                    verified = False
                else:
                    effective_entry = 0.0
                    effective_source = "reconciliation_required"
                    verified = False

                cost_basis_usd = quantity * effective_entry if effective_entry > 0 else broker_value
                now = datetime.now().isoformat()
                source = (existing or {}).get("position_source") or position_source
                chosen_strategy = (existing or {}).get("strategy") or strategy
                self.positions[symbol] = {
                    "entry_price": effective_entry,
                    "quantity": quantity,
                    "size_usd": cost_basis_usd,
                    "first_entry_time": (existing or {}).get("first_entry_time", now),
                    "last_entry_time": now,
                    "strategy": chosen_strategy,
                    "num_adds": int((existing or {}).get("num_adds", 0) or 0),
                    "previous_profit_pct": self._safe_float((existing or {}).get("previous_profit_pct")),
                    "position_source": source,
                    "entry_price_source": effective_source,
                    "cost_basis_verified": verified,
                    "auto_exit_blocked": not verified,
                    "auto_exit_block_reason": "" if verified else "unverified_cost_basis:reconciliation_required",
                    "last_broker_snapshot_value_usd": broker_value,
                    "last_broker_snapshot_price": current_price,
                }
                self._save_positions()

            changed = (
                existing is None
                or abs(old_qty - quantity) > max(1e-10, quantity * 1e-8)
                or abs(old_entry - effective_entry) > max(1e-8, abs(effective_entry) * 1e-8)
                or old_verified != verified
            )
            logger.warning(
                "POSITION_SNAPSHOT_SYNCED symbol=%s old_qty=%.8f new_qty=%.8f old_entry=$%.8f "
                "new_entry=$%.8f cost_basis=$%.2f broker_value=$%.2f changed=%s "
                "repaired_from_cost=%s cost_basis_verified=%s entry_source=%s",
                symbol, old_qty, quantity, old_entry, effective_entry, cost_basis_usd,
                broker_value, changed, repaired_from_cost, verified, effective_source,
            )
            if verified:
                self._persist_entry_price(symbol, effective_entry, quantity, effective_source)
            else:
                logger.critical(
                    "POSITION_COST_BASIS_RECONCILIATION_REQUIRED symbol=%s qty=%.8f adoption_mark=$%.8f source=%s auto_exit_blocked=true",
                    symbol, quantity, effective_entry, effective_source,
                )
            return True
        except Exception as exc:
            logger.error("Error synchronizing broker snapshot for %s: %s", symbol, exc)
            return False

    def track_exit(self, symbol: str, exit_quantity: float = None) -> bool:
        try:
            with self.lock:
                if symbol not in self.positions:
                    logger.warning("Attempted to exit untracked position: %s", symbol)
                    return False
                if exit_quantity is None:
                    del self.positions[symbol]
                    logger.info("Removed position %s (full exit)", symbol)
                    full_exit = True
                else:
                    full_exit = False
                    position = self.positions[symbol]
                    quantity = self._safe_float(position.get("quantity"))
                    remaining_qty = quantity - self._safe_float(exit_quantity)
                    if remaining_qty <= 0:
                        del self.positions[symbol]
                        logger.info("Removed position %s (partial exit cleared position)", symbol)
                        full_exit = True
                    else:
                        remaining_size = self._safe_float(position.get("size_usd")) * (remaining_qty / quantity)
                        position["quantity"] = remaining_qty
                        position["size_usd"] = remaining_size
                        logger.info("Reduced position %s: remaining_qty=%.8f, remaining_size=$%.2f", symbol, remaining_qty, remaining_size)
                self._save_positions()
            if full_exit and ENTRY_PRICE_STORE_AVAILABLE:
                try:
                    get_entry_price_store().clear(symbol)
                except Exception as exc:
                    logger.debug("[PositionTracker] entry_price_store clear failed for %s: %s", symbol, exc)
            return True
        except Exception as exc:
            logger.error("Error tracking exit for %s: %s", symbol, exc)
            return False

    def get_position(self, symbol: str) -> Optional[Dict]:
        with self.lock:
            return self.positions.get(symbol)

    def calculate_pnl(self, symbol: str, current_price: float) -> Optional[Dict]:
        position = self.get_position(symbol)
        if not position:
            return None
        entry_price = self._safe_float(position.get("entry_price"))
        quantity = self._safe_float(position.get("quantity"))
        entry_value = self._safe_float(position.get("size_usd"))
        current_value = quantity * self._safe_float(current_price)
        pnl_dollars = current_value - entry_value
        pnl_pct = pnl_dollars / entry_value if entry_value > 0 else 0.0
        if abs(pnl_pct) >= 1.0:
            logger.warning("⚠️ Large PnL detected for %s: %.2f%%", symbol, pnl_pct * 100.0)
        with self.lock:
            previous_profit = self._safe_float(position.get("previous_profit_pct"))
            position["previous_profit_pct"] = pnl_pct
            self._save_positions()
        return {
            "symbol": symbol,
            "entry_price": entry_price,
            "current_price": current_price,
            "quantity": quantity,
            "entry_value": entry_value,
            "current_value": current_value,
            "pnl_dollars": pnl_dollars,
            "pnl_percent": pnl_pct,
            "previous_profit_pct": previous_profit,
            "cost_basis_verified": position.get("cost_basis_verified") is True,
            "entry_price_source": position.get("entry_price_source"),
        }

    def get_all_positions(self) -> List[str]:
        with self.lock:
            return list(self.positions.keys())

    def sync_with_broker(self, broker_positions: List[Dict]) -> int:
        try:
            with self.lock:
                broker_symbols = {
                    str(pos.get("symbol") or "").strip()
                    for pos in (broker_positions or [])
                    if isinstance(pos, dict) and pos.get("symbol")
                }
                tracked_symbols = set(self.positions.keys())
                orphaned = tracked_symbols - broker_symbols
                if not orphaned:
                    return 0
                logger.info("Removing %d orphaned tracked positions: %s", len(orphaned), orphaned)
                for symbol in orphaned:
                    del self.positions[symbol]
                self._save_positions()
                return len(orphaned)
        except Exception as exc:
            logger.error("Error syncing with broker: %s", exc)
            return 0

    def clear_all(self) -> bool:
        try:
            with self.lock:
                count = len(self.positions)
                self.positions = {}
                self._save_positions()
            logger.warning("Cleared all %d tracked positions", count)
            return True
        except Exception as exc:
            logger.error("Error clearing positions: %s", exc)
            return False
