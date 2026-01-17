"""
NIJA Trade Signal Emitter
==========================

Emits trade signals when MASTER account executes orders.
These signals are consumed by the copy trade engine to replicate trades to user accounts.

Signal Flow:
    MASTER places order → emit_trade_signal() → Signal Queue → Copy Engine → USER trades
"""

import logging
import time
import queue
import threading
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger('nija.signals')


@dataclass
class TradeSignal:
    """
    Represents a trade signal emitted by the master account.
    
    This signal contains all information needed to replicate a trade to user accounts.
    """
    broker: str  # Exchange name (e.g., "coinbase", "kraken")
    symbol: str  # Trading pair (e.g., "BTC-USD")
    side: str  # "buy" or "sell"
    price: float  # Execution price (USD)
    size: float  # Position size in base currency or quote currency
    size_type: str  # "base" (crypto amount) or "quote" (USD amount)
    timestamp: float  # Unix timestamp when trade was executed
    order_id: str  # Master account order ID for tracking
    master_balance: float  # Master account balance at time of trade (for position sizing)
    
    def to_dict(self) -> Dict:
        """Convert signal to dictionary for logging/serialization."""
        return asdict(self)


class TradeSignalEmitter:
    """
    Thread-safe signal emitter for master account trades.
    
    Manages a queue of trade signals that are consumed by the copy trade engine.
    """
    
    def __init__(self, max_queue_size: int = 1000):
        """
        Initialize the signal emitter.
        
        Args:
            max_queue_size: Maximum number of signals to queue (prevents memory overflow)
        """
        self.signal_queue = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._total_signals_emitted = 0
        self._signals_dropped = 0
        
        logger.info("=" * 70)
        logger.info("📡 TRADE SIGNAL EMITTER INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"   Max queue size: {max_queue_size}")
        logger.info("=" * 70)
    
    def emit_signal(self, signal: TradeSignal) -> bool:
        """
        Emit a trade signal to be consumed by copy engine.
        
        Args:
            signal: TradeSignal object containing trade details
            
        Returns:
            True if signal was queued successfully, False if queue is full
        """
        try:
            with self._lock:
                # Try to add to queue without blocking
                try:
                    self.signal_queue.put_nowait(signal)
                    self._total_signals_emitted += 1
                    
                    logger.info("=" * 70)
                    logger.info("📡 TRADE SIGNAL EMITTED")
                    logger.info("=" * 70)
                    logger.info(f"   Broker: {signal.broker}")
                    logger.info(f"   Symbol: {signal.symbol}")
                    logger.info(f"   Side: {signal.side.upper()}")
                    logger.info(f"   Size: {signal.size} ({signal.size_type})")
                    logger.info(f"   Price: ${signal.price:.2f}")
                    logger.info(f"   Order ID: {signal.order_id}")
                    logger.info(f"   Master Balance: ${signal.master_balance:.2f}")
                    logger.info(f"   Total Signals Emitted: {self._total_signals_emitted}")
                    logger.info("=" * 70)
                    
                    return True
                    
                except queue.Full:
                    self._signals_dropped += 1
                    logger.error("=" * 70)
                    logger.error("❌ SIGNAL QUEUE FULL - SIGNAL DROPPED")
                    logger.error("=" * 70)
                    logger.error(f"   Symbol: {signal.symbol}")
                    logger.error(f"   Side: {signal.side}")
                    logger.error(f"   Total Signals Dropped: {self._signals_dropped}")
                    logger.error("   💡 Copy engine may be lagging - check for errors")
                    logger.error("=" * 70)
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error emitting signal: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def get_signal(self, timeout: float = 1.0) -> Optional[TradeSignal]:
        """
        Get the next signal from the queue (blocking with timeout).
        
        Args:
            timeout: Maximum seconds to wait for a signal
            
        Returns:
            TradeSignal if available, None if timeout or queue empty
        """
        try:
            signal = self.signal_queue.get(timeout=timeout)
            return signal
        except queue.Empty:
            return None
    
    def get_stats(self) -> Dict:
        """
        Get statistics about signal emission.
        
        Returns:
            Dictionary with emission stats
        """
        with self._lock:
            return {
                'total_emitted': self._total_signals_emitted,
                'signals_dropped': self._signals_dropped,
                'queue_size': self.signal_queue.qsize(),
                'queue_capacity': self.signal_queue.maxsize
            }


# Global singleton instance
_signal_emitter: Optional[TradeSignalEmitter] = None


def get_signal_emitter() -> TradeSignalEmitter:
    """
    Get the global signal emitter instance (singleton pattern).
    
    Returns:
        Global TradeSignalEmitter instance
    """
    global _signal_emitter
    if _signal_emitter is None:
        _signal_emitter = TradeSignalEmitter()
    return _signal_emitter


def emit_trade_signal(
    broker: str,
    symbol: str,
    side: str,
    price: float,
    size: float,
    size_type: str,
    order_id: str,
    master_balance: float
) -> bool:
    """
    Convenience function to emit a trade signal.
    
    This is the main entry point for emitting signals from broker code.
    
    Args:
        broker: Exchange name (e.g., "coinbase", "kraken")
        symbol: Trading pair (e.g., "BTC-USD")
        side: "buy" or "sell"
        price: Execution price in USD
        size: Position size
        size_type: "base" (crypto amount) or "quote" (USD amount)
        order_id: Order ID from the exchange
        master_balance: Current master account balance
        
    Returns:
        True if signal was emitted successfully
        
    Example:
        >>> emit_trade_signal(
        ...     broker="coinbase",
        ...     symbol="BTC-USD",
        ...     side="buy",
        ...     price=45000.0,
        ...     size=500.0,
        ...     size_type="quote",
        ...     order_id="abc-123-def",
        ...     master_balance=10000.0
        ... )
    """
    signal = TradeSignal(
        broker=broker,
        symbol=symbol,
        side=side,
        price=price,
        size=size,
        size_type=size_type,
        timestamp=time.time(),
        order_id=order_id,
        master_balance=master_balance
    )
    
    emitter = get_signal_emitter()
    return emitter.emit_signal(signal)
