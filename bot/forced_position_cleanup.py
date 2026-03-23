#!/usr/bin/env python3
"""
FORCED POSITION CLEANUP ENGINE
==============================
Implements aggressive position cleanup to address critical issues:

1. Force Dust Cleanup - Close ALL positions < $1 USD immediately
2. Retroactive Position Cap - Enforce hard cap by pruning excess positions
3. Multi-Account Support - Clean up both platform and user accounts

This runs independently of the trading loop to ensure cleanup happens
even when trading is paused or positions were adopted from legacy holdings.
"""

import logging
import time
import os
from typing import Dict, List, Tuple, Optional, Union, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.cleanup")

# Minimum USD value below which we skip closing (exchange won't accept the order)
EXCHANGE_MIN_CLOSE_USD = 1.00

# Hard floor for the dust-ignore block — positions below this USD value can
# NEVER be filled by any exchange (Coinbase, Kraken, Binance all reject
# sub-$1 market orders).
EXCHANGE_MIN_SELL_USD: float = 1.00

# PERFECT CLEANUP FLOW: how long (hours) an unsellable position is excluded from
# cap math before getting a fresh sell attempt.
UNSELLABLE_DECAY_HOURS: float = 12.0


class CleanupType(Enum):
    """Types of cleanup operations"""
    DUST = "DUST"  # Position < $1 USD
    CAP_EXCEEDED = "CAP_EXCEEDED"  # Over position limit
    UNHEALTHY = "UNHEALTHY"  # Low health score
    STAGNANT = "STAGNANT"  # No movement


def is_position_closable(pos_data: Dict, broker: Any, base_size=None) -> bool:
    """
    Pre-flight gate: verify a position is actually closable before a market-sell
    order is submitted to the broker.

    Returns False (UNSELLABLE / HARD BLOCK) when any of the following are true:
    - ``base_size`` is None or zero after all fallback resolution
    - Position USD value is below the exchange-minimum floor
    - Live broker balance for the base asset is zero (position already gone)

    Returns True only when all three checks pass.

    Args:
        pos_data:  Position metadata dict as produced by identify_* helpers.
        broker:    Broker instance; must expose ``get_asset_balance(asset)``.
        base_size: Resolved quantity (post Fix-#3).  Falls back to pos_data
                   fields when not supplied.
    """
    symbol   = pos_data.get('symbol', '')
    size_usd = pos_data.get('size_usd', 0) or 0

    # Resolve quantity from argument or position dict fields
    resolved_size = base_size or (
        pos_data.get('base_size') or
        pos_data.get('quantity') or
        pos_data.get('size')
    )

    # ── Check 1: must have a positive quantity ───────────────────────────────
    try:
        if not resolved_size or float(resolved_size) <= 0:
            logger.debug(
                "   is_position_closable: %s — zero / missing quantity (%s)",
                symbol, resolved_size,
            )
            return False
    except (TypeError, ValueError):
        logger.debug(
            "   is_position_closable: %s — non-numeric quantity (%s)",
            symbol, resolved_size,
        )
        return False

    # ── Check 2: USD value must clear the exchange floor ─────────────────────
    if size_usd < EXCHANGE_MIN_SELL_USD:
        logger.debug(
            "   is_position_closable: %s — $%.4f below exchange floor $%.2f",
            symbol, size_usd, EXCHANGE_MIN_SELL_USD,
        )
        return False

    # ── Check 3: live broker balance must confirm we still hold the asset ────
    try:
        base_asset   = symbol.split('-')[0].split('/')[0]
        live_balance = broker.get_asset_balance(base_asset)
        if live_balance is not None and float(live_balance) <= 0:
            logger.debug(
                "   is_position_closable: %s — live balance is zero (already closed?)",
                symbol,
            )
            return False
    except Exception as exc:
        # Non-fatal: balance API errors are surfaced by broker.close_position().
        logger.debug(
            "   is_position_closable: %s — balance check skipped (%s)",
            symbol, exc,
        )

    return True


class ForcedPositionCleanup:
    """
    Forces aggressive cleanup of dust positions and enforces hard position caps.
    
    Key Features:
    - Closes ALL positions < $1 USD (dust threshold)
    - Prunes excess positions to enforce hard cap retroactively
    - Supports multi-account cleanup (platform + users)
    - Comprehensive logging with profit status tracking
    """
    
    def __init__(self,
                 dust_threshold_usd: float = 1.00,
                 max_positions: int = 8,
                 dry_run: bool = False,
                 cancel_open_orders: bool = False,
                 startup_only: bool = False,
                 cancel_conditions: Optional[str] = None,
                 kill_all_on_startup: bool = False):
        """
        Initialize forced cleanup engine.
        
        Args:
            dust_threshold_usd: USD value threshold for dust positions
            max_positions: Hard cap on total positions
            dry_run: If True, log actions but don't execute trades
            cancel_open_orders: If True, cancel open orders during cleanup
            startup_only: If True with cancel_open_orders, only cancel on first run (nuclear mode)
            cancel_conditions: Selective cancellation conditions (e.g., "usd_value<1.0,rank>max_positions")
            kill_all_on_startup: If True, close ALL positions on the first startup cleanup run
                                  (ignores dust threshold and position cap — wipes the slate clean).
                                  Can also be activated via STARTUP_KILL_ALL_POSITIONS=true env var.
        """
        self.dust_threshold_usd = dust_threshold_usd
        self.max_positions = max_positions
        self.dry_run = dry_run
        self.has_run_startup = False  # Track if startup cleanup has run

        # Kill-all-on-startup: env var overrides the constructor argument
        _env_kill_all = os.getenv('STARTUP_KILL_ALL_POSITIONS', 'false').lower() in ['true', '1', 'yes']
        self.kill_all_on_startup = kill_all_on_startup or _env_kill_all

        # In-memory permanent blacklist — symbols added here are NEVER attempted
        # again in execute_cleanup, preventing the infinite retry loop.
        self._dust_blacklist: set = set()

        # PERFECT CLEANUP FLOW + CAP RESOLUTION ENGINE:
        # Maps symbol -> Unix timestamp when it was first marked unsellable.
        # Entries are evicted automatically after UNSELLABLE_DECAY_HOURS so the
        # position gets a fresh close attempt once the decay window expires.
        # While active, the symbol is excluded from cap math so unsellable
        # positions never permanently block new legitimate entries.
        self._unsellable_positions: Dict[str, float] = {}

        # Post-cleanup state — force re-synced after every cleanup run so
        # callers always have an accurate view of open positions.
        self.current_positions: List[Dict] = []
        self.open_positions_count: int = 0
        
        # Parse cancel_conditions if provided
        self.cancel_conditions = self._parse_cancel_conditions(cancel_conditions) if cancel_conditions else None
        
        # If cancel_conditions are provided, automatically enable cancel_open_orders
        if self.cancel_conditions:
            self.cancel_open_orders = True
            self.startup_only = startup_only
        else:
            self.cancel_open_orders = cancel_open_orders
            self.startup_only = startup_only
        
        # Load config from environment if not explicitly set via parameters
        # Only override if no explicit config was provided
        if not cancel_open_orders and not cancel_conditions:
            env_cancel = os.getenv('FORCED_CLEANUP_CANCEL_OPEN_ORDERS', 'false').lower() in ['true', '1', 'yes']
            env_startup_only = os.getenv('FORCED_CLEANUP_STARTUP_ONLY', 'false').lower() in ['true', '1', 'yes']
            env_conditions = os.getenv('FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF', '')
            
            if env_conditions:
                self.cancel_conditions = self._parse_cancel_conditions(env_conditions)
                self.cancel_open_orders = True  # Enable if conditions specified
            else:
                self.cancel_open_orders = env_cancel
            
            self.startup_only = env_startup_only
        
        logger.info("🧹 FORCED POSITION CLEANUP ENGINE INITIALIZED")
        logger.info(f"   Dust Threshold: ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Max Positions: {max_positions}")
        logger.info(f"   Dry Run: {dry_run}")
        if self.kill_all_on_startup:
            logger.warning("⚠️  KILL-ALL-ON-STARTUP ENABLED — all positions will be closed on first boot")
        else:
            logger.info(f"   Kill All On Startup: {self.kill_all_on_startup}")
        logger.info(f"   Cancel Open Orders: {self.cancel_open_orders}")
        if self.cancel_open_orders:
            if self.cancel_conditions:
                logger.info(f"   Cancellation Mode: SELECTIVE (conditions: {self.cancel_conditions})")
            elif self.startup_only:
                logger.info(f"   Cancellation Mode: NUCLEAR (startup-only)")
            else:
                logger.info(f"   Cancellation Mode: ALWAYS")

    # ------------------------------------------------------------------
    # Unsellable-position helpers  (PERFECT CLEANUP FLOW / CAP RESOLUTION)
    # ------------------------------------------------------------------

    def _expire_stale_unsellables(self) -> None:
        """Evict unsellable entries whose UNSELLABLE_DECAY_HOURS window has passed."""
        now = time.time()
        expired = [
            sym for sym, ts in self._unsellable_positions.items()
            if (now - ts) >= UNSELLABLE_DECAY_HOURS * 3600
        ]
        for sym in expired:
            del self._unsellable_positions[sym]
            logger.info(
                "♻️  Unsellable decay expired for %s — fresh close attempt allowed", sym
            )

    def _mark_unsellable(self, symbol: str) -> None:
        """Tag *symbol* as unsellable (first tag wins — preserves original timestamp)."""
        if symbol not in self._unsellable_positions:
            self._unsellable_positions[symbol] = time.time()
            logger.warning(
                "🔒 CAP RESOLUTION: %s marked unsellable for %.0fh — "
                "excluded from cap math until decay expires",
                symbol, UNSELLABLE_DECAY_HOURS,
            )

    def _is_tradable(self, symbol: str) -> bool:
        """Return True when *symbol* is NOT in the active unsellable window."""
        return symbol not in self._unsellable_positions

    def _filter_tradable(self, positions: List[Dict]) -> List[Dict]:
        """
        Return only the positions that are currently tradable.

        CAP RESOLUTION ENGINE: unsellable positions are excluded from this
        list so they do not inflate the cap count and block new entries.
        """
        tradable = [p for p in positions if self._is_tradable(p.get("symbol", ""))]
        excluded = len(positions) - len(tradable)
        if excluded:
            logger.info(
                "🔒 CAP RESOLUTION: %d unsellable position(s) excluded from cap math",
                excluded,
            )
        return tradable

    def _is_position_closable(self, pos_data: Dict, broker) -> bool:
        """
        Thin wrapper around ``auto_cleanup_engine.is_position_closable`` with a
        graceful fallback when the import is unavailable.

        Normalizes the position dict so it contains the ``quantity`` / ``base_size``
        fields that the underlying checker expects.
        """
        # Build a normalised dict the checker understands
        base_size = (
            pos_data.get("base_size")
            or pos_data.get("quantity")
            or pos_data.get("size")
            or pos_data.get("balance")
        )
        normalised = dict(pos_data, base_size=base_size)

        try:
            from bot.auto_cleanup_engine import is_position_closable
            return is_position_closable(normalised, broker)
        except Exception as exc:
            logger.debug("_is_position_closable: auto_cleanup_engine unavailable (%s), using fallback", exc)
            # Fallback: position is closable iff it has a positive base quantity and
            # its USD value meets the exchange minimum.
            size_usd = pos_data.get("size_usd", 0) or pos_data.get("usd_value", 0)
            return bool(base_size) and float(base_size) > 0 and size_usd >= EXCHANGE_MIN_SELL_USD

    def _parse_cancel_conditions(self, conditions_str: str) -> Dict[str, Union[float, bool]]:
        """
        Parse cancellation conditions from string format.
        
        Format: "usd_value<1.0,rank>max_positions"
        
        Supported conditions:
        - usd_value<X: Cancel if position USD value < X (float)
        - rank>max_positions: Cancel if position ranked for cap pruning (bool)
        
        Returns:
            Dict with parsed conditions (values can be float or bool).
            Returns empty dict if conditions_str is empty or all conditions are malformed.
        
        Error handling:
        - Malformed conditions are skipped with warning logs
        - Invalid numeric values are skipped with warnings
        - Missing operators are skipped with warnings
        """
        conditions = {}
        if not conditions_str:
            return conditions
        
        for condition in conditions_str.split(','):
            condition = condition.strip()
            
            try:
                if '<' in condition:
                    parts = condition.split('<')
                    if len(parts) != 2:
                        logger.warning(f"   ⚠️  Malformed condition (expected one '<'): {condition}")
                        continue
                    key, value = parts
                    try:
                        conditions[key.strip()] = float(value.strip())
                    except ValueError:
                        logger.warning(f"   ⚠️  Invalid numeric value in condition: {condition}")
                        continue
                elif '>' in condition:
                    parts = condition.split('>')
                    if len(parts) != 2:
                        logger.warning(f"   ⚠️  Malformed condition (expected one '>'): {condition}")
                        continue
                    key, value = parts
                    if value.strip() == 'max_positions':
                        conditions['rank_exceeds_cap'] = True
                    else:
                        logger.warning(f"   ⚠️  Unsupported '>' condition value: {value.strip()}")
                else:
                    logger.warning(f"   ⚠️  Condition missing operator ('<' or '>'): {condition}")
            except Exception as e:
                logger.warning(f"   ⚠️  Error parsing condition '{condition}': {e}")
                continue
        
        return conditions
    
    def _should_cancel_open_orders(self, position_data: Dict, is_startup: bool = False) -> bool:
        """
        Determine if open orders should be cancelled for this position.
        
        Args:
            position_data: Position data with cleanup metadata
            is_startup: Whether this is a startup cleanup
        
        Returns:
            True if open orders should be cancelled
        """
        # If open order cancellation is disabled, never cancel
        if not self.cancel_open_orders:
            return False
        
        # If startup-only mode and this is not startup, don't cancel
        if self.startup_only and not is_startup:
            return False
        
        # If startup-only mode and startup already ran, don't cancel
        if self.startup_only and self.has_run_startup:
            return False
        
        # If selective conditions are set, check them
        if self.cancel_conditions:
            size_usd = position_data.get('size_usd', 0)
            cleanup_type = position_data.get('cleanup_type', '')
            
            # Check USD value condition
            if 'usd_value' in self.cancel_conditions:
                if size_usd < self.cancel_conditions['usd_value']:
                    return True
            
            # Check rank condition (cap exceeded positions)
            if 'rank_exceeds_cap' in self.cancel_conditions:
                if cleanup_type == CleanupType.CAP_EXCEEDED.value:
                    return True
            
            # If conditions exist but none matched, don't cancel
            return False
        
        # Default: cancel if enabled and not in selective mode
        return True
    
    def _log_cap_violation_alert(self, user_id: str, current_count: int, max_positions: int):
        """
        Log cap violation alert for monitoring systems.
        
        Args:
            user_id: User identifier
            current_count: Current position count
            max_positions: Maximum allowed positions
        """
        alert_data = {
            'timestamp': datetime.now().isoformat(),
            'alert_type': 'POSITION_CAP_VIOLATION',
            'severity': 'CRITICAL',
            'user_id': user_id,
            'current_count': current_count,
            'max_positions': max_positions,
            'excess_count': current_count - max_positions
        }
        
        # Log as JSON for easy parsing by monitoring systems
        logger.error(f"🚨 CAP_VIOLATION_ALERT: {alert_data}")
        
        # Also log human-readable format
        logger.error(f"   User: {user_id}")
        logger.error(f"   Current Positions: {current_count}")
        logger.error(f"   Maximum Allowed: {max_positions}")
        logger.error(f"   Excess: {current_count - max_positions}")
        logger.error(f"   Action: Cleanup engine will attempt to reduce positions")
    
    def identify_dust_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify all positions below dust threshold.
        
        Args:
            positions: List of position dicts with 'symbol', 'size_usd', 'pnl_pct'
        
        Returns:
            List of dust positions with cleanup metadata
        """
        dust_positions = []
        
        for pos in positions:
            size_usd = pos.get('size_usd', 0) or pos.get('usd_value', 0)
            
            if size_usd > 0 and size_usd < self.dust_threshold_usd:
                # Preserve quantity so execute_cleanup can pass it as base_size to close_position()
                quantity = pos.get('quantity') or pos.get('base_size') or pos.get('size') or pos.get('balance')
                dust_positions.append({
                    'symbol': pos['symbol'],
                    'size_usd': size_usd,
                    'quantity': quantity,
                    'pnl_pct': pos.get('pnl_pct', 0),
                    'cleanup_type': CleanupType.DUST.value,
                    'reason': f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})',
                    'priority': 'HIGH'
                })
        
        return dust_positions
    
    def identify_cap_excess_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify positions to close when over the hard cap.
        
        Ranking criteria (in order):
        1. Lowest USD value (minimize capital impact)
        2. Worst P&L (cut losers first)
        3. Oldest age (if available)
        
        Args:
            positions: List of position dicts
        
        Returns:
            List of positions to close to meet cap
        """
        if len(positions) <= self.max_positions:
            return []
        
        excess_count = len(positions) - self.max_positions
        
        # Sort by ranking criteria
        ranked_positions = sorted(positions, key=lambda p: (
            p.get('size_usd', 0) or p.get('usd_value', 0),  # 1. Smallest first
            p.get('pnl_pct', 0) or 0,  # 2. Worst P&L first (handle None)
            -(p.get('entry_time', datetime.min).timestamp() if isinstance(p.get('entry_time'), datetime) else 0)  # 3. Oldest first (use min for missing dates)
        ))
        
        excess_positions = []
        for i in range(excess_count):
            pos = ranked_positions[i]
            # Preserve base asset quantity so execute_cleanup can pass it as
            # base_size to close_position() (fixes missing quantity on CAP_EXCEEDED)
            quantity = (
                pos.get('quantity') or
                pos.get('base_size') or
                pos.get('size')
            )
            excess_positions.append({
                'symbol': pos['symbol'],
                'size_usd': pos.get('size_usd', 0) or pos.get('usd_value', 0),
                'quantity': quantity,
                'pnl_pct': pos.get('pnl_pct', 0),
                'cleanup_type': CleanupType.CAP_EXCEEDED.value,
                'reason': f'Position cap exceeded ({len(positions)}/{self.max_positions})',
                'priority': 'HIGH'
            })
        
        return excess_positions
    
    def _get_open_orders_for_symbol(self, broker, symbol: str) -> List[Dict]:
        """
        Get open orders for a specific symbol.
        
        Handles broker API inconsistencies:
        - Some brokers use 'symbol' field (Coinbase, Alpaca)
        - Some brokers use 'pair' field (Kraken)
        
        Args:
            broker: Broker instance
            symbol: Trading symbol
        
        Returns:
            List of open order dicts
        """
        try:
            # Try to get all open orders
            if hasattr(broker, 'get_open_orders'):
                all_orders = broker.get_open_orders()
                if all_orders:
                    # Filter for this symbol (check both 'symbol' and 'pair' for compatibility)
                    return [order for order in all_orders if order.get('symbol') == symbol or order.get('pair') == symbol]
            
            # Fallback: check if broker has symbol-specific method
            if hasattr(broker, 'get_open_orders_for_symbol'):
                return broker.get_open_orders_for_symbol(symbol)
            
            return []
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to get open orders for {symbol}: {e}")
            return []
    
    def _cancel_open_orders_for_symbol(self, broker, symbol: str, is_startup: bool = False) -> Tuple[int, int]:
        """
        Cancel all open orders for a symbol.
        
        Handles broker API inconsistencies for order ID field names:
        - Coinbase: uses 'id' field
        - Kraken: uses 'txid' field  
        - Alpaca: uses 'order_id' or 'id' field
        
        Args:
            broker: Broker instance
            symbol: Trading symbol
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Tuple of (cancelled_count, failed_count)
        """
        open_orders = self._get_open_orders_for_symbol(broker, symbol)
        
        if not open_orders:
            return 0, 0
        
        cancelled = 0
        failed = 0
        
        for order in open_orders:
            # Try multiple field names for order ID (broker-specific)
            order_id = order.get('id') or order.get('order_id') or order.get('txid')
            if not order_id:
                logger.warning(f"   ⚠️  No order ID found for order on {symbol}")
                failed += 1
                continue
            
            try:
                if self.dry_run:
                    logger.warning(f"   [DRY RUN][OPEN_ORDER][WOULD_CANCEL] Order {order_id} on {symbol}")
                    cancelled += 1
                else:
                    logger.warning(f"   [OPEN_ORDER][CANCELLING] Order {order_id} on {symbol}")
                    if hasattr(broker, 'cancel_order'):
                        result = broker.cancel_order(order_id)
                        if result:
                            logger.warning(f"   ✅ [OPEN_ORDER][CANCELLED] Order {order_id}")
                            cancelled += 1
                        else:
                            logger.error(f"   ❌ [OPEN_ORDER][CANCEL_FAILED] Order {order_id}")
                            failed += 1
                    else:
                        logger.warning(f"   ⚠️  Broker does not support order cancellation")
                        failed += 1
                
                # Rate limiting
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"   ❌ [OPEN_ORDER][CANCEL_FAILED] Order {order_id}: {e}")
                failed += 1
        
        return cancelled, failed
    
    def execute_cleanup(self, 
                       positions_to_close: List[Dict],
                       broker,
                       account_id: str = "platform",
                       is_startup: bool = False) -> Tuple[int, int, int]:
        """
        Execute cleanup by closing positions and optionally cancelling open orders.

        PERFECT CLEANUP FLOW:
        - ``is_position_closable()`` is evaluated BEFORE ANY close attempt in
          every code path (including the kill-all startup path).
        - A position that fails the closable check is marked unsellable for
          UNSELLABLE_DECAY_HOURS and skipped without retrying.
        - Failed API closes are also marked unsellable and the loop continues
          (no ``break`` on first failure — zero loops, zero retries).

        Args:
            positions_to_close: List of positions with cleanup metadata
            broker: Broker instance to execute trades
            account_id: Account identifier for logging
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Tuple of (successful_closes, failed_closes, skipped_dust)
        """
        if not positions_to_close:
            return 0, 0, 0
        
        logger.warning(f"")
        logger.warning(f"🧹 EXECUTING FORCED CLEANUP: {account_id}")
        logger.warning(f"   Positions to close: {len(positions_to_close)}")
        logger.warning(f"")
        
        successful = 0
        failed = 0
        skipped = 0

        # Dedup guard — never process the same symbol twice in one cleanup run
        processed_symbols: set = set()

        for pos_data in positions_to_close:
            symbol = pos_data['symbol']

            # DEDUP GUARD: skip repeated entries for the same symbol
            if symbol in processed_symbols:
                logger.debug("   ⏭️ %s already processed this cleanup run — skipping", symbol)
                continue
            processed_symbols.add(symbol)

            cleanup_type = pos_data['cleanup_type']
            reason = pos_data['reason']
            pnl_pct = pos_data.get('pnl_pct', 0) or 0  # Handle None values
            size_usd = pos_data.get('size_usd', 0)
            # Normalize base asset size — check all field names used across brokers
            base_size = (
                pos_data.get('base_size') or
                pos_data.get('quantity') or
                pos_data.get('size')
            )

            # ── HARD BLOCK: permanent dust blacklist (check BEFORE size test) ─
            # Symbols already blacklisted are skipped immediately — never retry.
            if symbol in self._dust_blacklist:
                logger.debug("   ⏭️ %s is in dust blacklist — skipping permanently", symbol)
                skipped += 1
                continue

            # ── HARD BLOCK: new dust — blacklist + remove from system state ──
            # Positions below EXCHANGE_MIN_SELL_USD can NEVER be filled by any
            # exchange.  Add to the in-memory blacklist and skip — do NOT record
            # as a LOSS (it was never a trade).
            if size_usd > 0 and size_usd < EXCHANGE_MIN_SELL_USD:
                logger.warning(
                    f"   🚫 BLACKLISTED DUST: {symbol} (${size_usd:.4f}) — "
                    f"below exchange minimum ${EXCHANGE_MIN_SELL_USD:.2f}. "
                    f"Removed from system state permanently."
                )
                self._dust_blacklist.add(symbol)
                skipped += 1
                continue  # NEVER try again — not recorded as LOSS

            # ── PERFECT CLEANUP FLOW: closable guard BEFORE any close attempt ──
            # This check runs in EVERY code path — normal dust, cap-excess, and
            # kill-all — before any cancel_orders or close_position call is made.
            if not self._is_position_closable(pos_data, broker):
                logger.warning(
                    "   🚫 NOT CLOSABLE: %s (base_size below exchange minimum) — "
                    "marking unsellable for %.0fh, skipping",
                    symbol, UNSELLABLE_DECAY_HOURS,
                )
                self._mark_unsellable(symbol)
                skipped += 1
                continue  # PERFECT CLEANUP FLOW: no retry

            # All positions reaching here are tradeable — label WIN or LOSS only
            outcome = "WIN" if pnl_pct > 0 else "LOSS"
            
            logger.warning(f"")
            logger.warning(f"🧹 [{cleanup_type}][FORCED] {symbol}")
            logger.warning(f"   Account: {account_id}")
            logger.warning(f"   Reason: {reason}")
            logger.warning(f"   Size: ${size_usd:.2f}")
            if base_size is not None:
                logger.warning(f"   Base Size: {base_size}")
            logger.warning(f"   P&L: {pnl_pct*100:+.2f}%")
            logger.warning(f"   PROFIT_STATUS = PENDING → CONFIRMED")
            logger.warning(f"   OUTCOME = {outcome}")

            # Check if we should cancel open orders for this position
            should_cancel = self._should_cancel_open_orders(pos_data, is_startup)
            
            if should_cancel:
                logger.warning(f"   🔍 Checking for open orders...")
                cancelled, cancel_failed = self._cancel_open_orders_for_symbol(broker, symbol, is_startup)
                if cancelled > 0:
                    logger.warning(f"   ✅ Cancelled {cancelled} open order(s)")
                if cancel_failed > 0:
                    logger.warning(f"   ⚠️  Failed to cancel {cancel_failed} open order(s)")
            
            if self.dry_run:
                if should_cancel:
                    logger.warning(f"   [DRY RUN][WOULD_CLOSE] Position (after cancelling open orders)")
                else:
                    logger.warning(f"   [DRY RUN][WOULD_CLOSE] Position")
                successful += 1
                continue
            
            try:
                # Emergency fallback: if base_size is still unknown,
                # query the broker for the actual held quantity.
                if not base_size:
                    base_asset = symbol.split('-')[0].split('/')[0]
                    logger.warning(
                        f"   ⚠️ No base_size for {symbol}, "
                        f"forcing market sell using live balance"
                    )
                    base_size = broker.get_asset_balance(base_asset)
                    if not base_size or base_size <= 0:
                        logger.error(f"   ❌ Missing size for {symbol} — marking unsellable, skipping")
                        self._mark_unsellable(symbol)
                        failed += 1
                        continue  # PERFECT CLEANUP FLOW: no break, continue to next position

                # ── HARD STOP: pre-flight closability gate ───────────────────
                # Verify the position can actually be sold before touching the
                # broker API.  An unsellable position (zero live balance, below
                # exchange floor, or no valid quantity) is added to the dust
                # blacklist so it is *never retried* in this or future cleanup
                # cycles.  NOTE: this is intentionally permanent for the
                # lifetime of the process.  If underlying conditions change
                # (e.g. price recovers above the floor) a fresh bot restart
                # will clear the in-memory blacklist and allow re-evaluation.
                if not is_position_closable(pos_data, broker, base_size=base_size):
                    logger.warning(
                        f"🚫 HARD BLOCK (UNSELLABLE): {symbol} — skipping execution"
                    )
                    self._dust_blacklist.add(symbol)
                    skipped += 1
                    continue

                result = broker.close_position(symbol, base_size=base_size)
                
                if result and result.get('status') in ['filled', 'success']:
                    logger.warning(f"   ✅ CLOSED SUCCESSFULLY")
                    successful += 1
                else:
                    error = result.get('error', 'Unknown error') if result else 'No result'
                    logger.error(f"   ❌ CLOSE FAILED: {error}")
                    # PERFECT CLEANUP FLOW: mark unsellable and continue — no break
                    self._mark_unsellable(symbol)
                    failed += 1
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"   ❌ CLOSE FAILED: {e}")
                # PERFECT CLEANUP FLOW: mark unsellable and continue — no break
                self._mark_unsellable(symbol)
                failed += 1
        
        logger.warning(f"")
        logger.warning(f"🧹 Cleanup executed: {account_id}")
        logger.warning(f"   Successful: {successful}")
        logger.warning(f"   Skipped (below exchange minimum / unsellable): {skipped}")
        logger.warning(f"   Failed (marked unsellable): {failed}")
        logger.warning(f"")
        
        return successful, failed, skipped

    
    def _cleanup_user_all_brokers(self, 
                                  user_id: str,
                                  user_broker_dict: Dict,
                                  is_startup: bool = False) -> List[Dict]:
        """
        Cleanup positions for a single user across ALL their brokers.
        
        CRITICAL: Enforces position cap PER USER (not per broker).
        If a user has multiple brokers, we count positions across all brokers
        and enforce the cap at the user level.
        
        Args:
            user_id: User identifier
            user_broker_dict: Dict of {BrokerType: BaseBroker} for this user
            is_startup: Whether this is a startup cleanup
        
        Returns:
            List of cleanup results (one per broker)
        """
        logger.info(f"")
        logger.info(f"👤 USER: {user_id}")
        logger.info(f"-" * 70)
        
        # Step 1: Collect all positions across all user's brokers
        all_user_positions = []
        broker_positions_map = {}  # Maps position symbol to broker instance
        
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                continue
                
            try:
                positions = broker.get_positions()
                for pos in positions:
                    # Track which broker owns each position
                    symbol = pos.get('symbol', '')
                    if symbol:
                        all_user_positions.append(pos)
                        broker_positions_map[symbol] = broker
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to get positions from {broker_type.value}: {e}")
        
        total_user_positions = len(all_user_positions)
        logger.info(f"   📊 Active Positions: {total_user_positions} (across {len(user_broker_dict)} broker(s))")
        
        # Step 2: First pass - identify and close dust positions across all brokers
        dust_positions = self.identify_dust_positions(all_user_positions)
        dust_closed_total = 0
        
        if dust_positions:
            logger.warning(f"   🧹 Found {len(dust_positions)} dust positions")
            for dust_pos in dust_positions:
                symbol = dust_pos['symbol']
                broker = broker_positions_map.get(symbol)
                if broker:
                    account_id = self._get_account_id(user_id, broker)
                    success, failed, _skipped = self.execute_cleanup([dust_pos], broker, account_id, is_startup)
                    dust_closed_total += success
        
        # Step 3: Refresh positions after dust cleanup
        all_user_positions = []
        broker_positions_map = {}
        refresh_failures = []  # Track broker refresh failures
        
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                logger.warning(f"   ⚠️  {broker_type.value} broker not connected - skipping refresh")
                refresh_failures.append(broker_type.value)
                continue
                
            try:
                positions = broker.get_positions()
                if positions is None:
                    logger.error(f"   ❌ {broker_type.value} returned None for positions - broker may be disconnected")
                    refresh_failures.append(broker_type.value)
                    continue
                    
                if not isinstance(positions, list):
                    logger.error(f"   ❌ {broker_type.value} returned invalid positions type: {type(positions)}")
                    refresh_failures.append(broker_type.value)
                    continue
                    
                for pos in positions:
                    symbol = pos.get('symbol', '')
                    if symbol:
                        all_user_positions.append(pos)
                        broker_positions_map[symbol] = broker
                    else:
                        logger.warning(f"   ⚠️  Position from {broker_type.value} has no symbol - skipping")
                        
                logger.debug(f"   ✅ {broker_type.value}: Refreshed {len(positions)} position(s)")
            except Exception as e:
                logger.error(f"   ❌ Failed to refresh positions from {broker_type.value}: {e}")
                refresh_failures.append(broker_type.value)
        
        # Log refresh failures if any
        if refresh_failures:
            logger.warning(f"   ⚠️  Position refresh failed for {len(refresh_failures)} broker(s): {', '.join(refresh_failures)}")
            logger.warning(f"   ⚠️  Cap enforcement may be incomplete - retry recommended")
        
        # Filter out dust from cap check, then apply CAP RESOLUTION ENGINE:
        # unsellable positions are excluded so they don't inflate the cap count.
        non_dust_positions = [
            p for p in all_user_positions 
            if (p.get('size_usd', 0) or p.get('usd_value', 0)) >= self.dust_threshold_usd
        ]
        tradable_positions = self._filter_tradable(non_dust_positions)
        
        # Step 4: Enforce per-user position cap across all brokers
        cap_closed_total = 0
        current_count = len(tradable_positions)
        
        logger.info(f"   📊 Active Tradable Positions (after dust cleanup): {current_count}")
        
        cap_failed_total = 0
        if current_count > self.max_positions:
            logger.warning(f"   🔒 USER cap exceeded: {current_count}/{self.max_positions}")
            # Log alert for monitoring systems
            self._log_cap_violation_alert(user_id, current_count, self.max_positions)
            
            # Identify positions to close to meet cap
            cap_excess_positions = self.identify_cap_excess_positions(tradable_positions)
            
            # Close excess positions across all brokers, tracking failures
            for cap_pos in cap_excess_positions:
                symbol = cap_pos['symbol']
                broker = broker_positions_map.get(symbol)
                if broker:
                    account_id = self._get_account_id(user_id, broker)
                    success, failed, _skipped = self.execute_cleanup([cap_pos], broker, account_id, is_startup)
                    cap_closed_total += success
                    cap_failed_total += failed
        else:
            logger.info(f"   ✅ Under cap (no action needed)")
        
        # Step 5: Final position count for this user
        all_user_positions_final = []
        final_refresh_failures = []
        
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                logger.warning(f"   ⚠️  {broker_type.value} not connected for final verification")
                final_refresh_failures.append(broker_type.value)
                continue
                
            try:
                positions = broker.get_positions()
                if positions is None:
                    logger.error(f"   ❌ {broker_type.value} returned None in final count")
                    final_refresh_failures.append(broker_type.value)
                    continue
                    
                all_user_positions_final.extend(positions)
            except Exception as e:
                logger.error(f"   ❌ Final position count failed for {broker_type.value}: {e}")
                final_refresh_failures.append(broker_type.value)
        
        final_count = len(all_user_positions_final)
        
        # SAFETY VERIFICATION: Ensure user is under cap
        if final_count > self.max_positions:
            logger.error(f"   ❌ SAFETY VIOLATION: User {user_id} final count {final_count} exceeds cap {self.max_positions}")
            logger.error(f"      This should never happen - per-user cleanup failed!")
            
            # Provide diagnostic information
            if refresh_failures or final_refresh_failures:
                logger.error(f"   ⚠️  POSSIBLE CAUSE: Some brokers failed to refresh positions")
                all_failures = set(refresh_failures + final_refresh_failures)
                logger.error(f"      Failed brokers: {', '.join(all_failures)}")
                logger.error(f"   💡 RECOMMENDATION: Retry cleanup or manually verify these brokers")
            elif cap_failed_total > 0:
                logger.error(f"   ⚠️  POSSIBLE CAUSE: {cap_failed_total} position close operation(s) failed (broker API errors)")
                logger.error(f"   💡 RECOMMENDATION: Check broker API connectivity and retry cleanup once connected")
            else:
                logger.error(f"   ⚠️  POSSIBLE CAUSE: Position close operations failed")
                logger.error(f"   💡 RECOMMENDATION: Check broker API status and retry cleanup")
        else:
            logger.info(f"   ✅ SAFETY VERIFIED: User {user_id} final count {final_count} ≤ cap {self.max_positions}")
            if final_refresh_failures:
                logger.warning(f"   ⚠️  Note: Some brokers failed final verification: {', '.join(final_refresh_failures)}")
        
        logger.info(f"")
        logger.info(f"   👤 USER {user_id} SUMMARY:")
        logger.info(f"      Initial: {total_user_positions} positions")
        logger.info(f"      Dust closed: {dust_closed_total}")
        logger.info(f"      Cap excess closed: {cap_closed_total}")
        if cap_failed_total > 0:
            logger.warning(f"      Cap excess close failures: {cap_failed_total} (broker API errors)")
        logger.info(f"      Final: {final_count} positions")
        if dust_closed_total > 0 or cap_closed_total > 0:
            logger.warning(f"      🧹 Cleanup executed for user {user_id}")
        logger.info(f"")
        
        # Return results for each broker (for compatibility with existing summary)
        # Note: To avoid double-counting, we only report dust_closed and cap_closed once
        results = []
        totals_reported = False  # Flag to ensure totals reported only once
        
        for broker_type, broker in user_broker_dict.items():
            if broker and broker.connected:
                account_id = self._get_account_id(user_id, broker)
                # Note: We already did cleanup above, so just report final state
                try:
                    final_positions = broker.get_positions()
                    results.append({
                        'account_id': account_id,
                        'user_id': user_id,
                        'user_total_initial': total_user_positions,  # Total across all brokers (for context)
                        'initial_positions': len(final_positions),  # Current count for this broker
                        'dust_closed': dust_closed_total if not totals_reported else 0,  # Report once
                        'cap_closed': cap_closed_total if not totals_reported else 0,  # Report once
                        'final_positions': len(final_positions),  # Current count for this broker
                        'status': 'cleaned'
                    })
                    totals_reported = True  # Mark totals as reported
                except Exception:
                    results.append({
                        'account_id': account_id,
                        'user_id': user_id,
                        'user_total_initial': total_user_positions,
                        'initial_positions': 0,
                        'dust_closed': 0,
                        'cap_closed': 0,
                        'final_positions': 0,
                        'status': 'error'
                    })
        
        return results
    
    def _get_account_id(self, user_id: str, broker) -> str:
        """
        Helper to construct account ID from user_id and broker.
        
        Args:
            user_id: User identifier
            broker: Broker instance
            
        Returns:
            Account ID string (e.g., "user_user123_coinbase")
        """
        broker_type_str = broker.broker_type.value if hasattr(broker, 'broker_type') else 'unknown'
        return f"user_{user_id}_{broker_type_str}"

    def cleanup_single_account(self,
                               broker,
                               account_id: str = "platform",
                               is_startup: bool = False) -> Dict:
        """
        Run forced cleanup on a single account.
        
        Args:
            broker: Broker instance for the account
            account_id: Account identifier for logging
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Cleanup result summary
        """
        logger.info(f"🔍 Scanning account: {account_id}")

        # PERFECT CLEANUP FLOW: expire any unsellable entries whose 12h window
        # has passed so stale exclusions never permanently block enforcement.
        self._expire_stale_unsellables()
        
        if not broker or not hasattr(broker, 'get_positions'):
            logger.error(f"   ❌ Invalid broker for {account_id}")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'error'
            }
        
        # Get current positions
        try:
            positions = broker.get_positions()
        except Exception as e:
            logger.error(f"   ❌ Failed to get positions: {e}")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'error'
            }
        
        initial_count = len(positions)
        logger.info(f"   Initial positions: {initial_count}")
        
        if initial_count == 0:
            logger.info(f"   ✅ No positions to clean up")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'clean'
            }
        
        # Step 1: Identify and close dust positions
        dust_positions = self.identify_dust_positions(positions)
        dust_closed = 0

        # KILL-ALL MODE: On startup, close every position regardless of size or cap.
        # This wipes the slate clean so the bot restarts with zero open positions.
        if is_startup and self.kill_all_on_startup and not self.has_run_startup:
            kill_all_positions = []
            for pos in positions:
                size_usd = pos.get('size_usd', 0) or pos.get('usd_value', 0)
                quantity = pos.get('quantity') or pos.get('base_size') or pos.get('size') or pos.get('balance')
                kill_all_positions.append({
                    'symbol': pos['symbol'],
                    'size_usd': size_usd,
                    'quantity': quantity,
                    'pnl_pct': pos.get('pnl_pct', 0),
                    'cleanup_type': 'kill_all_startup',
                    'reason': 'Startup kill-all: wiping slate clean for fresh start',
                    'priority': 'CRITICAL',
                })
            if kill_all_positions:
                logger.warning(f"   💀 KILL-ALL-ON-STARTUP: Closing all {len(kill_all_positions)} positions")

                # ── CANCEL ALL OPEN ORDERS FIRST ─────────────────────────────
                # Free up any locked capital held by open limit/stop orders
                # before closing positions so the sells go through cleanly.
                try:
                    if hasattr(broker, 'cancel_all_orders'):
                        cancelled_count = broker.cancel_all_orders()
                        if cancelled_count:
                            logger.warning(f"   🗑️  KILL-ALL: Cancelled {cancelled_count} open order(s)")
                        else:
                            logger.info(f"   🗑️  KILL-ALL: No open orders to cancel")
                except Exception as cancel_err:
                    logger.warning(f"   ⚠️  KILL-ALL: cancel_all_orders failed (continuing): {cancel_err}")

                # ── RE-FETCH BALANCE AFTER ORDER CANCELLATION ─────────────────
                try:
                    if hasattr(broker, 'get_balance'):
                        balance = broker.get_balance()
                    elif hasattr(broker, 'get_account_balance'):
                        balance = broker.get_account_balance()
                    else:
                        balance = None
                    if balance is not None:
                        logger.info(f"   💰 KILL-ALL: Balance after order cancel: {balance}")
                except Exception as bal_err:
                    logger.warning(f"   ⚠️  KILL-ALL: balance re-fetch failed (continuing): {bal_err}")

                kill_success, kill_fail, kill_skipped = self.execute_cleanup(
                    kill_all_positions, broker, account_id, is_startup
                )
                dust_closed = kill_success
                # Mark startup done and return early — no further cap check needed
                self.has_run_startup = True
                try:
                    final_positions = broker.get_positions()
                except Exception:
                    final_positions = []

                final_count = len(final_positions)

                # ── FORCE RE-SYNC ────────────────────────────────────────────
                self.current_positions = final_positions
                self.open_positions_count = len(final_positions)

                # ── CLEAN SLATE CHECK ────────────────────────────────────────
                if kill_success + kill_skipped == initial_count:
                    logger.info(
                        f"   ✅ CLEAN SLATE (including {kill_skipped} dust exclusion(s)): "
                        f"{initial_count} → {final_count} positions"
                    )
                else:
                    logger.warning(f"   ✅ KILL-ALL COMPLETE: {initial_count} → {final_count} positions")
                return {
                    'account_id': account_id,
                    'initial_positions': initial_count,
                    'dust_closed': dust_closed,
                    'skipped_dust': kill_skipped,
                    'cap_closed': 0,
                    'final_positions': final_count,
                    'status': 'kill_all_complete',
                }

        if dust_positions:
            logger.warning(f"   🧹 Found {len(dust_positions)} dust positions")
            dust_success, dust_fail, _dust_skipped = self.execute_cleanup(
                dust_positions, broker, account_id, is_startup
            )
            dust_closed = dust_success
        
        # Step 2: Refresh positions and check cap
        try:
            positions = broker.get_positions()
        except Exception as e:
            logger.error(f"   ❌ Failed to refresh positions: {e}")
            positions = []
        
        # Filter out dust positions from cap check, then apply CAP RESOLUTION ENGINE:
        # unsellable positions are excluded so they don't inflate the cap count.
        non_dust_positions = [
            p for p in positions 
            if (p.get('size_usd', 0) or p.get('usd_value', 0)) >= self.dust_threshold_usd
        ]
        tradable_positions = self._filter_tradable(non_dust_positions)
        
        cap_excess_positions = self.identify_cap_excess_positions(tradable_positions)
        cap_closed = 0
        if cap_excess_positions:
            logger.warning(
                f"   🔒 Position cap exceeded: {len(tradable_positions)} tradable"
                f"/{self.max_positions} max  (unsellable excluded from count)"
            )
            cap_success, cap_fail, _cap_skipped = self.execute_cleanup(
                cap_excess_positions, broker, account_id, is_startup
            )
            cap_closed = cap_success
        
        # Mark startup as complete if this was a startup cleanup
        if is_startup:
            self.has_run_startup = True
        
        # Final position count — FORCE RE-SYNC from broker
        try:
            final_positions = broker.get_positions()
        except Exception:
            final_positions = []

        final_count = len(final_positions)

        # ── FORCE RE-SYNC: update instance state so callers have latest view ─
        self.current_positions = final_positions
        self.open_positions_count = len(final_positions)
        
        # SAFETY VERIFICATION: Ensure we're actually under cap
        if final_count > self.max_positions:
            logger.error(f"   ❌ SAFETY VIOLATION: Final count {final_count} still exceeds cap {self.max_positions}")
            logger.error(f"      This should never happen - cleanup failed to enforce cap!")
        else:
            logger.info(f"   ✅ SAFETY VERIFIED: Final count {final_count} ≤ cap {self.max_positions}")
        
        return {
            'account_id': account_id,
            'initial_positions': initial_count,
            'dust_closed': dust_closed,
            'cap_closed': cap_closed,
            'final_positions': final_count,
            'status': 'cleaned'
        }
    
    def cleanup_all_accounts(self, multi_account_manager, is_startup: bool = False) -> Dict:
        """
        Run forced cleanup across all accounts (platform + users).
        
        CRITICAL: Enforces position caps PER USER across all their brokers.
        Each user is limited to max_positions (default 8) total positions.
        
        Args:
            multi_account_manager: MultiAccountBrokerManager instance
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Summary of cleanup across all accounts
        """
        logger.warning("=" * 70)
        logger.warning("🧹 FORCED CLEANUP: ALL ACCOUNTS")
        logger.warning("=" * 70)
        
        results = []
        
        # Cleanup platform accounts
        logger.info("")
        logger.info("📊 PLATFORM ACCOUNTS")
        logger.info("-" * 70)
        
        for broker_type, broker in multi_account_manager.platform_brokers.items():
            if broker and broker.connected:
                account_id = f"platform_{broker_type.value}"
                result = self.cleanup_single_account(broker, account_id, is_startup)
                results.append(result)
        
        # Cleanup user accounts - ENFORCE PER-USER POSITION CAPS
        logger.info("")
        logger.info("👥 USER ACCOUNTS")
        logger.info("-" * 70)
        
        for user_id, user_broker_dict in multi_account_manager.user_brokers.items():
            # Process all brokers for this user together to enforce per-user cap
            user_result = self._cleanup_user_all_brokers(
                user_id, 
                user_broker_dict, 
                is_startup
            )
            results.extend(user_result)
        
        # Summary
        total_initial = sum(r['initial_positions'] for r in results)
        total_dust = sum(r['dust_closed'] for r in results)
        total_cap = sum(r['cap_closed'] for r in results)
        total_final = sum(r['final_positions'] for r in results)
        
        logger.warning("")
        logger.warning("=" * 70)
        logger.warning("🧹 Cleanup executed - ALL ACCOUNTS")
        logger.warning("=" * 70)
        logger.warning(f"   Accounts processed: {len(results)}")
        logger.warning(f"   Initial total positions: {total_initial}")
        logger.warning(f"   Dust positions closed: {total_dust}")
        logger.warning(f"   Cap excess closed: {total_cap}")
        logger.warning(f"   Final total positions: {total_final}")
        logger.warning(f"   Total reduced by: {total_initial - total_final}")
        logger.warning("=" * 70)
        logger.warning("")
        
        return {
            'accounts_processed': len(results),
            'initial_total': total_initial,
            'dust_closed': total_dust,
            'cap_closed': total_cap,
            'final_total': total_final,
            'reduction': total_initial - total_final,
            'details': results
        }


# Example standalone usage
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    )
    
    # Example: Test with mock positions
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True
    )
    
    # Mock positions
    mock_positions = [
        {'symbol': 'BTC-USD', 'size_usd': 50.0, 'pnl_pct': 0.02},
        {'symbol': 'ETH-USD', 'size_usd': 0.50, 'pnl_pct': -0.01},  # Dust
        {'symbol': 'SOL-USD', 'size_usd': 30.0, 'pnl_pct': 0.01},
        {'symbol': 'MATIC-USD', 'size_usd': 0.75, 'pnl_pct': 0.005},  # Dust
        {'symbol': 'AVAX-USD', 'size_usd': 25.0, 'pnl_pct': -0.015},
        {'symbol': 'DOT-USD', 'size_usd': 20.0, 'pnl_pct': 0.008},
        {'symbol': 'LINK-USD', 'size_usd': 15.0, 'pnl_pct': -0.02},
        {'symbol': 'UNI-USD', 'size_usd': 10.0, 'pnl_pct': 0.005},
        {'symbol': 'AAVE-USD', 'size_usd': 5.0, 'pnl_pct': -0.01},
        {'symbol': 'ATOM-USD', 'size_usd': 3.0, 'pnl_pct': 0.003},  # 10th position (over cap)
    ]
    
    # Test dust identification
    dust = cleanup.identify_dust_positions(mock_positions)
    logger.info(f"\n🧹 Dust positions identified: {len(dust)}")
    
    # Test cap excess identification
    cap_excess = cleanup.identify_cap_excess_positions(mock_positions)
    logger.info(f"🔒 Cap excess positions: {len(cap_excess)}")
