"""
NIJA Activity Feed - Decision Truth Layer

This module provides comprehensive logging of ALL trading decisions:
- Trade signals (accepted and executed)
- Rejected signals with reasons
- Filter blocks (pair quality, fees, risk limits)
- Position exits (profit targets, stop losses, signals)
- Fee impact analysis
- Stablecoin routing decisions

This is the "Decision Truth" layer - it shows everything NIJA considers,
not just what executes on the exchange (which is "Execution Proof").

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import pandas as pd

logger = logging.getLogger("nija.activity_feed")


class ActivityType(Enum):
    """Types of activities logged in the feed."""
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_ACCEPTED = "signal_accepted"
    SIGNAL_REJECTED = "signal_rejected"
    TRADE_EXECUTED = "trade_executed"
    TRADE_FAILED = "trade_failed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    PARTIAL_EXIT = "partial_exit"
    STOP_LOSS_HIT = "stop_loss_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    FILTER_BLOCK = "filter_block"
    FEE_BLOCK = "fee_block"
    RISK_LIMIT_HIT = "risk_limit_hit"
    STABLECOIN_ROUTED = "stablecoin_routed"
    STABLECOIN_BLOCKED = "stablecoin_blocked"
    BROKER_SELECTED = "broker_selected"
    MIN_SIZE_BLOCK = "min_size_block"


@dataclass
class ActivityEvent:
    """
    Single activity event in the feed.
    
    Each event captures a decision point in NIJA's trading logic.
    """
    timestamp: str
    event_type: str  # ActivityType enum value
    symbol: str
    message: str
    details: Dict[str, Any]
    level: str = "INFO"  # INFO, WARNING, ERROR, SUCCESS
    broker: Optional[str] = None
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class ActivityFeed:
    """
    Comprehensive activity feed for all trading decisions.
    
    This is the "Decision Truth" layer that shows:
    - What signals NIJA generated
    - Which signals were accepted/rejected
    - Why rejections happened
    - What trades actually executed
    - Position management decisions
    - Filter and risk management blocks
    """
    
    def __init__(self, feed_dir: str = "./data/activity_feed"):
        """
        Initialize activity feed.
        
        Args:
            feed_dir: Directory to store activity feed files
        """
        self.feed_dir = feed_dir
        os.makedirs(feed_dir, exist_ok=True)
        
        # Activity files
        self.activity_file = os.path.join(feed_dir, "activity_feed.jsonl")
        self.summary_file = os.path.join(feed_dir, "daily_summary.json")
        
        # In-memory cache for recent activity (last 1000 events)
        self.recent_events: List[ActivityEvent] = []
        self.max_recent_events = 1000
        
        # Load recent events if file exists
        self._load_recent_events()
        
        logger.info(f"Activity Feed initialized: {feed_dir}")
    
    def _load_recent_events(self) -> None:
        """Load recent events from file into memory."""
        if not os.path.exists(self.activity_file):
            return
        
        try:
            with open(self.activity_file, 'r') as f:
                # Read last N lines
                lines = f.readlines()
                recent_lines = lines[-self.max_recent_events:]
                
                for line in recent_lines:
                    try:
                        event_dict = json.loads(line.strip())
                        event = ActivityEvent(**event_dict)
                        self.recent_events.append(event)
                    except Exception as e:
                        logger.debug(f"Error loading event: {e}")
        except Exception as e:
            logger.error(f"Error loading recent events: {e}")
    
    def log_signal_generated(self, symbol: str, signal_type: str, 
                            ai_score: float, confidence: float,
                            details: Dict[str, Any]) -> None:
        """
        Log when a trading signal is generated.
        
        Args:
            symbol: Trading pair
            signal_type: 'long', 'short', or 'neutral'
            ai_score: AI signal score
            confidence: Confidence level (0-1)
            details: Additional signal details
        """
        message = f"Signal generated: {signal_type.upper()} {symbol} (score: {ai_score:.2f}, confidence: {confidence:.2%})"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.SIGNAL_GENERATED.value,
            symbol=symbol,
            message=message,
            details={
                'signal_type': signal_type,
                'ai_score': ai_score,
                'confidence': confidence,
                **details
            },
            level="INFO"
        )
        
        self._log_event(event)
    
    def log_signal_rejected(self, symbol: str, signal_type: str,
                           rejection_reason: str, details: Dict[str, Any]) -> None:
        """
        Log when a signal is rejected.
        
        Args:
            symbol: Trading pair
            signal_type: 'long', 'short', or 'neutral'
            rejection_reason: Why the signal was rejected
            details: Additional context
        """
        message = f"❌ Signal REJECTED: {signal_type.upper()} {symbol} - {rejection_reason}"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.SIGNAL_REJECTED.value,
            symbol=symbol,
            message=message,
            details={
                'signal_type': signal_type,
                'rejection_reason': rejection_reason,
                **details
            },
            level="WARNING"
        )
        
        self._log_event(event)
    
    def log_filter_block(self, symbol: str, filter_name: str,
                        filter_reason: str, details: Dict[str, Any]) -> None:
        """
        Log when a trade is blocked by filters.
        
        Args:
            symbol: Trading pair
            filter_name: Name of the filter that blocked the trade
            filter_reason: Specific reason for blocking
            details: Filter-specific details
        """
        message = f"🚫 FILTER BLOCK: {symbol} - {filter_name}: {filter_reason}"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.FILTER_BLOCK.value,
            symbol=symbol,
            message=message,
            details={
                'filter_name': filter_name,
                'filter_reason': filter_reason,
                **details
            },
            level="INFO"
        )
        
        self._log_event(event)
    
    def log_fee_block(self, symbol: str, broker: str,
                     estimated_fees: float, position_size: float,
                     details: Dict[str, Any]) -> None:
        """
        Log when a trade is blocked due to excessive fees.
        
        Args:
            symbol: Trading pair
            broker: Broker name
            estimated_fees: Estimated fee amount
            position_size: Position size
            details: Fee calculation details
        """
        fee_pct = (estimated_fees / position_size * 100) if position_size > 0 else 0
        message = f"💸 FEE BLOCK: {symbol} on {broker} - ${estimated_fees:.2f} ({fee_pct:.2f}% of position)"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.FEE_BLOCK.value,
            symbol=symbol,
            message=message,
            broker=broker,
            details={
                'estimated_fees': estimated_fees,
                'position_size': position_size,
                'fee_percentage': fee_pct,
                **details
            },
            level="WARNING"
        )
        
        self._log_event(event)
    
    def log_min_size_block(self, symbol: str, broker: str,
                          attempted_size: float, min_size: float,
                          tier: str, details: Dict[str, Any]) -> None:
        """
        Log when a trade is blocked due to minimum size requirements.
        
        Args:
            symbol: Trading pair
            broker: Broker name
            attempted_size: Attempted trade size
            min_size: Minimum required size
            tier: User tier (SAVER, INVESTOR, etc.)
            details: Additional context
        """
        message = f"📏 MIN SIZE BLOCK: {symbol} - ${attempted_size:.2f} < ${min_size:.2f} (tier: {tier})"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.MIN_SIZE_BLOCK.value,
            symbol=symbol,
            message=message,
            broker=broker,
            details={
                'attempted_size': attempted_size,
                'min_size': min_size,
                'tier': tier,
                **details
            },
            level="INFO"
        )
        
        self._log_event(event)
    
    def log_stablecoin_routed(self, symbol: str, from_broker: str,
                             to_broker: str, reason: str) -> None:
        """
        Log when a stablecoin trade is routed to a specific broker.
        
        Args:
            symbol: Trading pair (e.g., ETH-USDT)
            from_broker: Original broker considered
            to_broker: Broker selected for execution
            reason: Why it was routed
        """
        message = f"🔀 STABLECOIN ROUTED: {symbol} - {from_broker} → {to_broker} ({reason})"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.STABLECOIN_ROUTED.value,
            symbol=symbol,
            message=message,
            broker=to_broker,
            details={
                'from_broker': from_broker,
                'to_broker': to_broker,
                'reason': reason
            },
            level="INFO"
        )
        
        self._log_event(event)
    
    def log_stablecoin_blocked(self, symbol: str, broker: str, reason: str) -> None:
        """
        Log when a stablecoin trade is blocked.
        
        Args:
            symbol: Trading pair
            broker: Broker that blocked it
            reason: Why it was blocked
        """
        message = f"⛔ STABLECOIN BLOCKED: {symbol} on {broker} - {reason}"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.STABLECOIN_BLOCKED.value,
            symbol=symbol,
            message=message,
            broker=broker,
            details={
                'reason': reason
            },
            level="WARNING"
        )
        
        self._log_event(event)
    
    def log_trade_executed(self, symbol: str, broker: str,
                          side: str, size: float, price: float,
                          details: Dict[str, Any]) -> None:
        """
        Log successful trade execution.
        
        Args:
            symbol: Trading pair
            broker: Broker where trade executed
            side: 'buy' or 'sell'
            size: Trade size
            price: Execution price
            details: Trade details
        """
        message = f"✅ EXECUTED: {side.upper()} {size:.2f} {symbol} @ ${price:.2f} on {broker}"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.TRADE_EXECUTED.value,
            symbol=symbol,
            message=message,
            broker=broker,
            details={
                'side': side,
                'size': size,
                'price': price,
                **details
            },
            level="SUCCESS"
        )
        
        self._log_event(event)
    
    def log_position_closed(self, symbol: str, broker: str,
                           exit_reason: str, pnl: float,
                           details: Dict[str, Any]) -> None:
        """
        Log position closure.
        
        Args:
            symbol: Trading pair
            broker: Broker
            exit_reason: Why position was closed
            pnl: Profit/loss
            details: Additional details
        """
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        message = f"{pnl_emoji} POSITION CLOSED: {symbol} - {exit_reason} (P&L: ${pnl:.2f})"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.POSITION_CLOSED.value,
            symbol=symbol,
            message=message,
            broker=broker,
            details={
                'exit_reason': exit_reason,
                'pnl': pnl,
                **details
            },
            level="SUCCESS" if pnl >= 0 else "INFO"
        )
        
        self._log_event(event)
    
    def log_risk_limit_hit(self, limit_type: str, limit_value: float,
                          current_value: float, details: Dict[str, Any]) -> None:
        """
        Log when a risk limit is hit.
        
        Args:
            limit_type: Type of limit (daily_loss, max_positions, etc.)
            limit_value: Limit threshold
            current_value: Current value that hit the limit
            details: Additional context
        """
        message = f"⚠️ RISK LIMIT HIT: {limit_type} - {current_value:.2f}/{limit_value:.2f}"
        
        event = ActivityEvent(
            timestamp=datetime.now().isoformat(),
            event_type=ActivityType.RISK_LIMIT_HIT.value,
            symbol="ALL",
            message=message,
            details={
                'limit_type': limit_type,
                'limit_value': limit_value,
                'current_value': current_value,
                **details
            },
            level="ERROR"
        )
        
        self._log_event(event)
    
    def _log_event(self, event: ActivityEvent) -> None:
        """
        Log an activity event to file and memory.
        
        Args:
            event: ActivityEvent to log
        """
        # Add to recent events
        self.recent_events.append(event)
        if len(self.recent_events) > self.max_recent_events:
            self.recent_events.pop(0)
        
        # Write to file (JSONL format - one JSON object per line)
        try:
            with open(self.activity_file, 'a') as f:
                f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Error writing to activity feed: {e}")
        
        # Log to console
        log_func = logger.info
        if event.level == "WARNING":
            log_func = logger.warning
        elif event.level == "ERROR":
            log_func = logger.error
        
        log_func(event.message)
    
    def get_recent_events(self, n: int = 100, 
                         event_type: Optional[str] = None,
                         symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent activity events.
        
        Args:
            n: Number of events to return
            event_type: Filter by event type (optional)
            symbol: Filter by symbol (optional)
        
        Returns:
            List of event dictionaries
        """
        events = self.recent_events.copy()
        
        # Filter by event type
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Filter by symbol
        if symbol:
            events = [e for e in events if e.symbol == symbol]
        
        # Return most recent N events
        events = events[-n:]
        events.reverse()  # Most recent first
        
        return [e.to_dict() for e in events]
    
    def get_rejection_reasons(self, hours: int = 24) -> Dict[str, int]:
        """
        Get counts of rejection reasons in the last N hours.
        
        Args:
            hours: Time window in hours
        
        Returns:
            Dict of reason -> count
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        reasons = {}
        for event in self.recent_events:
            event_time = datetime.fromisoformat(event.timestamp)
            if event_time < cutoff:
                continue
            
            if event.event_type in [
                ActivityType.SIGNAL_REJECTED.value,
                ActivityType.FILTER_BLOCK.value,
                ActivityType.FEE_BLOCK.value,
                ActivityType.MIN_SIZE_BLOCK.value,
                ActivityType.STABLECOIN_BLOCKED.value
            ]:
                reason = event.details.get('rejection_reason') or \
                        event.details.get('filter_reason') or \
                        event.details.get('reason') or \
                        'unknown'
                reasons[reason] = reasons.get(reason, 0) + 1
        
        return reasons
    
    def get_activity_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get summary statistics for the last N hours.
        
        Args:
            hours: Time window in hours
        
        Returns:
            Dict with activity statistics
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        summary = {
            'period_hours': hours,
            'total_events': 0,
            'signals_generated': 0,
            'signals_accepted': 0,
            'signals_rejected': 0,
            'trades_executed': 0,
            'positions_closed': 0,
            'filter_blocks': 0,
            'fee_blocks': 0,
            'min_size_blocks': 0,
            'risk_limits_hit': 0,
            'rejection_reasons': {}
        }
        
        for event in self.recent_events:
            event_time = datetime.fromisoformat(event.timestamp)
            if event_time < cutoff:
                continue
            
            summary['total_events'] += 1
            
            if event.event_type == ActivityType.SIGNAL_GENERATED.value:
                summary['signals_generated'] += 1
            elif event.event_type == ActivityType.SIGNAL_ACCEPTED.value:
                summary['signals_accepted'] += 1
            elif event.event_type == ActivityType.SIGNAL_REJECTED.value:
                summary['signals_rejected'] += 1
            elif event.event_type == ActivityType.TRADE_EXECUTED.value:
                summary['trades_executed'] += 1
            elif event.event_type == ActivityType.POSITION_CLOSED.value:
                summary['positions_closed'] += 1
            elif event.event_type == ActivityType.FILTER_BLOCK.value:
                summary['filter_blocks'] += 1
            elif event.event_type == ActivityType.FEE_BLOCK.value:
                summary['fee_blocks'] += 1
            elif event.event_type == ActivityType.MIN_SIZE_BLOCK.value:
                summary['min_size_blocks'] += 1
            elif event.event_type == ActivityType.RISK_LIMIT_HIT.value:
                summary['risk_limits_hit'] += 1
        
        summary['rejection_reasons'] = self.get_rejection_reasons(hours)
        
        return summary
    
    def clear_old_events(self, days: int = 30) -> int:
        """
        Archive events older than N days to a separate file.
        
        Args:
            days: Age threshold in days
        
        Returns:
            Number of events archived
        """
        if not os.path.exists(self.activity_file):
            return 0
        
        cutoff = datetime.now() - timedelta(days=days)
        archive_file = os.path.join(
            self.feed_dir,
            f"activity_archive_{datetime.now().strftime('%Y%m%d')}.jsonl"
        )
        
        kept_events = []
        archived_events = []
        
        try:
            with open(self.activity_file, 'r') as f:
                for line in f:
                    try:
                        event_dict = json.loads(line.strip())
                        event_time = datetime.fromisoformat(event_dict['timestamp'])
                        
                        if event_time < cutoff:
                            archived_events.append(line)
                        else:
                            kept_events.append(line)
                    except Exception as e:
                        logger.debug(f"Error processing event: {e}")
            
            # Write archived events
            if archived_events:
                with open(archive_file, 'w') as f:
                    f.writelines(archived_events)
            
            # Rewrite main file with only recent events
            with open(self.activity_file, 'w') as f:
                f.writelines(kept_events)
            
            logger.info(f"Archived {len(archived_events)} events to {archive_file}")
            return len(archived_events)
            
        except Exception as e:
            logger.error(f"Error archiving events: {e}")
            return 0


# Global activity feed instance
_activity_feed_instance: Optional[ActivityFeed] = None


def get_activity_feed() -> ActivityFeed:
    """
    Get the global activity feed instance.
    
    Returns:
        ActivityFeed instance
    """
    global _activity_feed_instance
    
    if _activity_feed_instance is None:
        _activity_feed_instance = ActivityFeed()
    
    return _activity_feed_instance
