"""
NIJA Market Readiness Gate
===========================

Global market readiness check before entries.
Prevents trading in unfavorable conditions to protect capital and improve profitability.

Three operating modes:
1. AGGRESSIVE: Full trading when all conditions are optimal
2. CAUTIOUS: Limited trading when some conditions are met
3. IDLE: No entries, exits only

Philosophy:
- Stop trading when edge ≈ 0
- Preserve capital
- Wait for expansion, not noise
- When trades happen, they matter

Profitability comes from fewer, higher-quality trades.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger("nija.market_readiness")

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    def scalar(x):
        """Convert indicator value to float, handling tuples/lists"""
        if isinstance(x, (tuple, list)):
            if len(x) == 0:
                raise ValueError("Cannot convert empty tuple/list to scalar")
            return float(x[0])
        return float(x)


class MarketMode(Enum):
    """Market readiness operating modes"""
    IDLE = "idle"              # No entries, exits only
    CAUTIOUS = "cautious"      # Limited trading with reduced size
    AGGRESSIVE = "aggressive"  # Full trading with normal position sizing


@dataclass
class MarketConditions:
    """Current market condition measurements"""
    atr_pct: float = 0.0
    adx: float = 0.0
    volume_percentile: float = 0.0
    spread_pct: float = 0.0
    win_rate_24h: float = 0.0
    consecutive_non_meaningful_wins: int = 0
    circuit_breaker_cleared_hours_ago: float = 999.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MarketConditions':
        return cls(**data)


@dataclass
class ReadinessState:
    """State tracking for market readiness"""
    trades_24h: list = None  # List of trade results from last 24h
    last_circuit_breaker_clear: Optional[str] = None  # ISO timestamp
    
    def __post_init__(self):
        if self.trades_24h is None:
            self.trades_24h = []
    
    def to_dict(self) -> Dict:
        return {
            'trades_24h': self.trades_24h,
            'last_circuit_breaker_clear': self.last_circuit_breaker_clear
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ReadinessState':
        return cls(**data)


class MarketReadinessGate:
    """
    Market Readiness Gate - Guards entries based on market quality
    
    AGGRESSIVE MODE (Full trading):
    - ATR ≥ 0.6%
    - ADX ≥ 25
    - Volume percentile ≥ 60%
    - Spread ≤ 0.15%
    - Win rate (24h rolling) ≥ 45%
    → Full position sizing allowed
    
    CAUTIOUS MODE (Limited trading):
    - ATR 0.4%–0.6%
    - ADX 18–25
    - Volume ≥ 40%
    → Size capped at 15–25%
    → Only A+ setups (score ≥ 85)
    
    IDLE MODE (No entries):
    - ATR < 0.4%
    - Spread > expected move
    - 3 consecutive non-meaningful wins
    - Circuit breaker recently cleared (<2h)
    → No entries, exits only
    """
    
    # Thresholds for AGGRESSIVE mode (all must be true)
    AGGRESSIVE_ATR_MIN = 0.006        # 0.6%
    AGGRESSIVE_ADX_MIN = 25.0
    AGGRESSIVE_VOLUME_PERCENTILE_MIN = 60.0
    AGGRESSIVE_SPREAD_MAX = 0.0015    # 0.15%
    AGGRESSIVE_WIN_RATE_MIN = 0.45    # 45%
    
    # Thresholds for CAUTIOUS mode (some conditions met)
    CAUTIOUS_ATR_MIN = 0.004          # 0.4%
    CAUTIOUS_ATR_MAX = 0.006          # 0.6%
    CAUTIOUS_ADX_MIN = 18.0
    CAUTIOUS_ADX_MAX = 25.0
    CAUTIOUS_VOLUME_PERCENTILE_MIN = 40.0
    
    # Position sizing for CAUTIOUS mode
    CAUTIOUS_SIZE_MIN = 0.15          # 15%
    CAUTIOUS_SIZE_MAX = 0.25          # 25%
    CAUTIOUS_MIN_SCORE = 85           # Only A+ setups
    
    # IDLE mode triggers
    IDLE_ATR_MAX = 0.004              # 0.4%
    IDLE_NON_MEANINGFUL_WIN_THRESHOLD = 3
    IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS = 2.0
    
    # Meaningful win threshold (must make > fees to count)
    MEANINGFUL_WIN_THRESHOLD = 0.002  # 0.2% profit (covers fees + some profit)
    
    def __init__(self, state_file: str = ".market_readiness_state.json"):
        """
        Initialize Market Readiness Gate
        
        Args:
            state_file: Path to state persistence file
        """
        self.state_file = state_file
        self.state = self._load_state()
        
        logger.info("✅ Market Readiness Gate initialized")
        logger.info(f"   AGGRESSIVE: ATR≥{self.AGGRESSIVE_ATR_MIN*100}%, ADX≥{self.AGGRESSIVE_ADX_MIN}, "
                   f"Vol≥{self.AGGRESSIVE_VOLUME_PERCENTILE_MIN}%, WinRate≥{self.AGGRESSIVE_WIN_RATE_MIN*100}%")
        logger.info(f"   CAUTIOUS: ATR {self.CAUTIOUS_ATR_MIN*100}%-{self.CAUTIOUS_ATR_MAX*100}%, "
                   f"ADX {self.CAUTIOUS_ADX_MIN}-{self.CAUTIOUS_ADX_MAX}, Score≥{self.CAUTIOUS_MIN_SCORE}")
        logger.info(f"   IDLE: ATR<{self.IDLE_ATR_MAX*100}%, 3 non-meaningful wins, or circuit breaker <2h")
    
    def _load_state(self) -> ReadinessState:
        """Load state from file or create new"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                return ReadinessState.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to load readiness state: {e}")
                return ReadinessState()
        return ReadinessState()
    
    def _save_state(self):
        """Persist state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save readiness state: {e}")
    
    def _cleanup_old_trades(self):
        """Remove trades older than 24 hours"""
        if not self.state.trades_24h:
            return
        
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self.state.trades_24h = [
            trade for trade in self.state.trades_24h
            if datetime.fromisoformat(trade['timestamp']) > cutoff
        ]
        self._save_state()
    
    def record_trade_result(self, profit_pct: float, timestamp: Optional[datetime] = None):
        """
        Record a trade result for win rate tracking
        
        Args:
            profit_pct: Profit/loss as percentage (e.g., 0.015 for 1.5%)
            timestamp: Trade timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        trade = {
            'timestamp': timestamp.isoformat(),
            'profit_pct': profit_pct,
            'meaningful': profit_pct >= self.MEANINGFUL_WIN_THRESHOLD
        }
        
        self.state.trades_24h.append(trade)
        self._cleanup_old_trades()
        self._save_state()
        
        logger.debug(f"Recorded trade: {profit_pct*100:.2f}% {'(meaningful)' if trade['meaningful'] else ''}")
    
    def record_circuit_breaker_clear(self, timestamp: Optional[datetime] = None):
        """
        Record when circuit breaker was cleared
        
        Args:
            timestamp: Clear timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        self.state.last_circuit_breaker_clear = timestamp.isoformat()
        self._save_state()
        
        logger.warning(f"⚠️ Circuit breaker cleared at {timestamp.isoformat()} - "
                      f"IDLE mode for {self.IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS}h")
    
    def calculate_win_rate_24h(self) -> Tuple[float, int, int]:
        """
        Calculate rolling 24h win rate (meaningful wins only)
        
        Returns:
            Tuple of (win_rate, total_trades, meaningful_wins)
        """
        self._cleanup_old_trades()
        
        if not self.state.trades_24h:
            return 0.0, 0, 0
        
        total = len(self.state.trades_24h)
        winning = sum(1 for t in self.state.trades_24h if t['profit_pct'] > 0)
        meaningful_wins = sum(1 for t in self.state.trades_24h if t.get('meaningful', False))
        
        win_rate = winning / total if total > 0 else 0.0
        
        return win_rate, total, meaningful_wins
    
    def count_consecutive_non_meaningful_wins(self) -> int:
        """
        Count consecutive recent wins that were non-meaningful (< 0.2%)
        
        Returns:
            Number of consecutive non-meaningful wins
        """
        if not self.state.trades_24h:
            return 0
        
        # Sort by timestamp, most recent first
        sorted_trades = sorted(
            self.state.trades_24h,
            key=lambda t: datetime.fromisoformat(t['timestamp']),
            reverse=True
        )
        
        count = 0
        for trade in sorted_trades:
            # Only count wins
            if trade['profit_pct'] <= 0:
                break
            
            # If win is not meaningful, increment
            if not trade.get('meaningful', False):
                count += 1
            else:
                # Stop at first meaningful win
                break
        
        return count
    
    def get_hours_since_circuit_breaker_clear(self) -> float:
        """
        Get hours since circuit breaker was last cleared
        
        Returns:
            Hours since clear (999.0 if never cleared)
        """
        if not self.state.last_circuit_breaker_clear:
            return 999.0
        
        clear_time = datetime.fromisoformat(self.state.last_circuit_breaker_clear)
        hours = (datetime.utcnow() - clear_time).total_seconds() / 3600.0
        
        return hours
    
    def check_market_readiness(
        self,
        atr: float,
        current_price: float,
        adx: float,
        volume_percentile: float,
        spread_pct: float,
        entry_score: Optional[float] = None
    ) -> Tuple[MarketMode, MarketConditions, Dict]:
        """
        Check market readiness and determine operating mode
        
        Args:
            atr: Average True Range value
            current_price: Current asset price
            adx: Average Directional Index
            volume_percentile: Current volume percentile (0-100)
            spread_pct: Bid-ask spread as percentage
            entry_score: Optional entry quality score (0-100)
        
        Returns:
            Tuple of (mode, conditions, details)
        """
        # Calculate ATR as percentage
        atr_pct = atr / current_price if current_price > 0 else 0.0
        
        # Get win rate metrics
        win_rate, total_trades, meaningful_wins = self.calculate_win_rate_24h()
        
        # Check consecutive non-meaningful wins
        consecutive_non_meaningful = self.count_consecutive_non_meaningful_wins()
        
        # Check circuit breaker cooldown
        hours_since_cb_clear = self.get_hours_since_circuit_breaker_clear()
        
        # Build conditions object
        conditions = MarketConditions(
            atr_pct=atr_pct,
            adx=adx,
            volume_percentile=volume_percentile,
            spread_pct=spread_pct,
            win_rate_24h=win_rate,
            consecutive_non_meaningful_wins=consecutive_non_meaningful,
            circuit_breaker_cleared_hours_ago=hours_since_cb_clear
        )
        
        # Check IDLE mode triggers (any of these = IDLE)
        idle_reasons = []
        
        if atr_pct < self.IDLE_ATR_MAX:
            idle_reasons.append(f"ATR too low ({atr_pct*100:.3f}% < {self.IDLE_ATR_MAX*100:.3f}%)")
        
        if spread_pct > atr_pct:
            idle_reasons.append(f"Spread exceeds expected move ({spread_pct*100:.3f}% > {atr_pct*100:.3f}%)")
        
        if consecutive_non_meaningful >= self.IDLE_NON_MEANINGFUL_WIN_THRESHOLD:
            idle_reasons.append(f"{consecutive_non_meaningful} consecutive non-meaningful wins")
        
        if hours_since_cb_clear < self.IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS:
            idle_reasons.append(f"Circuit breaker cleared {hours_since_cb_clear:.1f}h ago (< 2h)")
        
        if idle_reasons:
            details = {
                'mode': MarketMode.IDLE.value,
                'reasons': idle_reasons,
                'message': 'Market not paying traders right now',
                'allow_entries': False,
                'allow_exits': True,
                'position_size_multiplier': 0.0
            }
            logger.info(f"🛑 IDLE MODE: {'; '.join(idle_reasons)}")
            return MarketMode.IDLE, conditions, details
        
        # Check AGGRESSIVE mode (all conditions must be true)
        aggressive_checks = {
            'atr': atr_pct >= self.AGGRESSIVE_ATR_MIN,
            'adx': adx >= self.AGGRESSIVE_ADX_MIN,
            'volume': volume_percentile >= self.AGGRESSIVE_VOLUME_PERCENTILE_MIN,
            'spread': spread_pct <= self.AGGRESSIVE_SPREAD_MAX,
            'win_rate': win_rate >= self.AGGRESSIVE_WIN_RATE_MIN or total_trades < 10  # Grace period
        }
        
        if all(aggressive_checks.values()):
            details = {
                'mode': MarketMode.AGGRESSIVE.value,
                'reasons': ['All conditions optimal'],
                'message': 'Market ready for aggressive trading',
                'allow_entries': True,
                'allow_exits': True,
                'position_size_multiplier': 1.0,
                'min_entry_score': None  # No score requirement
            }
            logger.info(f"🚀 AGGRESSIVE MODE: ATR={atr_pct*100:.2f}%, ADX={adx:.1f}, "
                       f"Vol={volume_percentile:.0f}%, WR={win_rate*100:.1f}%")
            return MarketMode.AGGRESSIVE, conditions, details
        
        # Check CAUTIOUS mode (some conditions met)
        cautious_checks = {
            'atr': self.CAUTIOUS_ATR_MIN <= atr_pct <= self.CAUTIOUS_ATR_MAX,
            'adx': self.CAUTIOUS_ADX_MIN <= adx <= self.CAUTIOUS_ADX_MAX,
            'volume': volume_percentile >= self.CAUTIOUS_VOLUME_PERCENTILE_MIN
        }
        
        # At least 2 out of 3 cautious conditions
        if sum(cautious_checks.values()) >= 2:
            # Check if entry score meets A+ threshold (if provided)
            allow_entry = True
            if entry_score is not None and entry_score < self.CAUTIOUS_MIN_SCORE:
                allow_entry = False
            
            details = {
                'mode': MarketMode.CAUTIOUS.value,
                'reasons': [k for k, v in cautious_checks.items() if v],
                'message': 'Market conditions marginal - trade cautiously',
                'allow_entries': allow_entry,
                'allow_exits': True,
                'position_size_multiplier': 0.20,  # 20% of normal size
                'min_entry_score': self.CAUTIOUS_MIN_SCORE
            }
            
            if allow_entry:
                logger.info(f"⚠️ CAUTIOUS MODE: Limited trading (20% size, score≥85)")
            else:
                logger.info(f"⚠️ CAUTIOUS MODE: Entry score {entry_score:.0f} < {self.CAUTIOUS_MIN_SCORE} (blocked)")
            
            return MarketMode.CAUTIOUS, conditions, details
        
        # Default to IDLE if no mode matches
        details = {
            'mode': MarketMode.IDLE.value,
            'reasons': ['Conditions insufficient for AGGRESSIVE or CAUTIOUS'],
            'message': 'Market not paying traders right now',
            'allow_entries': False,
            'allow_exits': True,
            'position_size_multiplier': 0.0
        }
        logger.info(f"🛑 IDLE MODE (default): Insufficient conditions")
        return MarketMode.IDLE, conditions, details
    
    def get_position_size_adjustment(self, base_size: float, mode: MarketMode) -> float:
        """
        Adjust position size based on market mode
        
        Args:
            base_size: Base position size (e.g., 0.05 for 5%)
            mode: Current market mode
        
        Returns:
            Adjusted position size
        """
        if mode == MarketMode.AGGRESSIVE:
            return base_size  # No adjustment
        elif mode == MarketMode.CAUTIOUS:
            # Cap at 15-25% range
            cautious_size = base_size * 0.20  # 20% of normal
            return max(min(cautious_size, self.CAUTIOUS_SIZE_MAX), self.CAUTIOUS_SIZE_MIN)
        else:  # IDLE
            return 0.0  # No entries allowed
