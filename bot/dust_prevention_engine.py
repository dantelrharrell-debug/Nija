"""
DUST PREVENTION ENGINE
======================
Requirement B: Kill dust accumulation

Prevents "own a little of everything" by enforcing:
1. Position caps (hard limits on concurrent positions)
2. Asset ranking (only trade the BEST opportunities)
3. Forced exits on stagnation (close positions that aren't moving)

Philosophy: "Own a few things with intention" not "spray and pray"
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionHealth:
    """Health score for a position"""
    symbol: str
    entry_time: datetime
    current_pnl_pct: float
    age_hours: float
    last_movement_hours: float  # Hours since last significant P&L change
    score: float  # 0-100, higher = healthier (keep), lower = unhealthy (close)
    reason: str


class DustPreventionEngine:
    """
    Prevents dust accumulation by:
    - Enforcing strict position limits
    - Ranking positions by quality
    - Forcing exits on stagnant positions
    """
    
    # Scoring thresholds (class-level constants)
    PNL_STRONG_PROFIT_THRESHOLD = 0.02  # > 2% profit
    PNL_PROFIT_THRESHOLD = 0.005  # > 0.5% profit
    PNL_STRONG_LOSS_THRESHOLD = -0.02  # > 2% loss
    PNL_LOSS_THRESHOLD = -0.005  # > 0.5% loss
    
    # Age thresholds
    AGE_OLD_HOURS = 12.0
    AGE_AGING_HOURS = 6.0
    AGE_FRESH_HOURS = 1.0
    
    def __init__(self, 
                 max_positions: int = 5,
                 stagnation_hours: float = 4.0,
                 min_pnl_movement: float = 0.002):
        """
        Args:
            max_positions: Maximum concurrent positions (default: 5 for quality focus)
            stagnation_hours: Hours without P&L movement before forced exit
            min_pnl_movement: Minimum P&L% change to consider "movement" (0.2%)
        """
        self.max_positions = max_positions
        self.stagnation_hours = stagnation_hours
        self.min_pnl_movement = min_pnl_movement
        
        # Track P&L movement over time
        self.position_history: Dict[str, List[Tuple[datetime, float]]] = {}
        
        logger.info(f"🧹 DustPreventionEngine initialized:")
        logger.info(f"   Max Positions: {max_positions} (QUALITY > QUANTITY)")
        logger.info(f"   Stagnation Limit: {stagnation_hours}h")
        logger.info(f"   Min Movement: {min_pnl_movement*100:.2f}%")
    
    def update_position_pnl(self, symbol: str, pnl_pct: float):
        """Track P&L changes to detect stagnation"""
        now = datetime.now()
        if symbol not in self.position_history:
            self.position_history[symbol] = []
        self.position_history[symbol].append((now, pnl_pct))
        
        # Keep only last 24 hours of history
        cutoff = now - timedelta(hours=24)
        self.position_history[symbol] = [
            (t, p) for t, p in self.position_history[symbol] if t > cutoff
        ]
    
    def get_hours_since_last_movement(self, symbol: str) -> float:
        """
        Calculate hours since last significant P&L movement
        Returns stagnation_hours if no movement detected
        """
        if symbol not in self.position_history or len(self.position_history[symbol]) < 2:
            return 0.0  # New position, give it time
        
        history = self.position_history[symbol]
        now = datetime.now()
        
        # Find the last time P&L changed by more than min_pnl_movement
        for i in range(len(history) - 1, 0, -1):
            curr_pnl = history[i][1]
            prev_pnl = history[i-1][1]
            
            if abs(curr_pnl - prev_pnl) >= self.min_pnl_movement:
                # Found movement!
                time_since = (now - history[i][0]).total_seconds() / 3600
                return time_since
        
        # No significant movement found - return age of oldest record
        oldest_time = history[0][0]
        return (now - oldest_time).total_seconds() / 3600
    
    def score_position_health(self, 
                              symbol: str,
                              entry_time: datetime,
                              current_pnl_pct: float) -> PositionHealth:
        """
        Score a position's health (0-100, higher = keep, lower = exit)
        
        Scoring factors:
        - P&L performance (most important)
        - Movement vs stagnation
        - Age (older positions scored lower)
        """
        now = datetime.now()
        age_hours = (now - entry_time).total_seconds() / 3600
        stagnation_hours = self.get_hours_since_last_movement(symbol)
        
        score = 50.0  # Neutral baseline
        reasons = []
        
        # Factor 1: P&L Performance (±30 points)
        if current_pnl_pct > self.PNL_STRONG_PROFIT_THRESHOLD:
            score += 30
            reasons.append("strong profit")
        elif current_pnl_pct > self.PNL_PROFIT_THRESHOLD:
            score += 15
            reasons.append("profitable")
        elif current_pnl_pct < self.PNL_STRONG_LOSS_THRESHOLD:
            score -= 30
            reasons.append("strong loss")
        elif current_pnl_pct < self.PNL_LOSS_THRESHOLD:
            score -= 15
            reasons.append("losing")
        else:
            reasons.append("flat P&L")
        
        # Factor 2: Stagnation (±25 points)
        if stagnation_hours > self.stagnation_hours:
            score -= 25
            reasons.append(f"stagnant {stagnation_hours:.1f}h")
        elif stagnation_hours < 0.5:
            score += 10
            reasons.append("active movement")
        
        # Factor 3: Age (±15 points) - prefer younger positions
        if age_hours > self.AGE_OLD_HOURS:
            score -= 15
            reasons.append(f"old {age_hours:.1f}h")
        elif age_hours > self.AGE_AGING_HOURS:
            score -= 5
            reasons.append(f"aging {age_hours:.1f}h")
        elif age_hours < self.AGE_FRESH_HOURS:
            score += 5
            reasons.append("fresh")
        
        # Factor 4: Stale losers get worst score
        if current_pnl_pct < 0 and stagnation_hours > self.stagnation_hours / 2:
            score -= 20
            reasons.append("STALE LOSER")
        
        reason = ", ".join(reasons)
        
        return PositionHealth(
            symbol=symbol,
            entry_time=entry_time,
            current_pnl_pct=current_pnl_pct,
            age_hours=age_hours,
            last_movement_hours=stagnation_hours,
            score=max(0, min(100, score)),  # Clamp 0-100
            reason=reason
        )
    
    def identify_positions_to_close(self,
                                     positions: List[Dict],
                                     force_to_limit: bool = True) -> List[Dict]:
        """
        Identify which positions should be closed
        
        Args:
            positions: List of position dicts with 'symbol', 'entry_time', 'pnl_pct'
            force_to_limit: If True and over limit, force close worst positions
        
        Returns:
            List of positions to close with reasons
        """
        if not positions:
            return []
        
        # Score all positions
        health_scores = []
        for pos in positions:
            # Update P&L tracking
            self.update_position_pnl(pos['symbol'], pos.get('pnl_pct', 0))
            
            # Score health
            health = self.score_position_health(
                symbol=pos['symbol'],
                entry_time=pos.get('entry_time', datetime.now()),
                current_pnl_pct=pos.get('pnl_pct', 0)
            )
            health_scores.append((pos, health))
        
        # Sort by health score (lowest first = worst positions first)
        health_scores.sort(key=lambda x: x[1].score)
        
        to_close = []
        
        # Rule 1: Force close if over position limit
        if force_to_limit and len(positions) > self.max_positions:
            excess = len(positions) - self.max_positions
            logger.warning(f"🧹 DUST CLEANUP: {len(positions)} positions exceeds limit of {self.max_positions}")
            logger.warning(f"   Forcing exit of {excess} worst positions")
            
            for i in range(excess):
                pos, health = health_scores[i]
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Position cap exceeded (score: {health.score:.0f}, {health.reason})',
                    'health_score': health.score,
                    'priority': 'HIGH',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pos.get('pnl_pct', 0)
                })
        
        # Rule 2: Close stagnant positions (score < 30)
        for pos, health in health_scores:
            # Skip if already marked for closure
            if any(c['symbol'] == pos['symbol'] for c in to_close):
                continue
            
            if health.score < 30:
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Unhealthy position (score: {health.score:.0f}, {health.reason})',
                    'health_score': health.score,
                    'priority': 'MEDIUM',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pos.get('pnl_pct', 0)
                })
            elif health.last_movement_hours > self.stagnation_hours:
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Stagnant (no movement for {health.last_movement_hours:.1f}h)',
                    'health_score': health.score,
                    'priority': 'MEDIUM',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pos.get('pnl_pct', 0)
                })
        
        # Log results with profit status transitions
        if to_close:
            logger.warning(f"🧹 Identified {len(to_close)} positions for dust cleanup:")
            for tc in to_close:
                logger.warning(f"   {tc['priority']}: {tc['symbol']} - {tc['reason']}")
                # PROFIT_STATUS transition logging
                logger.warning(f"   PROFIT_STATUS = PENDING → CONFIRMED (forced exit)")
        else:
            logger.info(f"✅ All {len(positions)} positions healthy (under limit of {self.max_positions})")
        
        return to_close
    
    def log_forced_exit(self, symbol: str, reason: str, current_pnl_pct: float):
        """
        Log a forced exit with explicit profit status transition
        
        This is the critical logging that ensures forced exits are tracked
        as confirmed wins/losses, not left in pending state.
        
        Args:
            symbol: The symbol being force-closed
            reason: Why it's being closed
            current_pnl_pct: Current P&L percentage
        """
        outcome = "WIN" if current_pnl_pct > 0 else "LOSS"
        logger.warning(f"")
        logger.warning(f"🧹 FORCED EXIT: {symbol}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Current P&L: {current_pnl_pct*100:+.2f}%")
        logger.warning(f"   PROFIT_STATUS = PENDING → CONFIRMED")
        logger.warning(f"   OUTCOME = {outcome} (no neutral, no pending)")
        logger.warning(f"")
    
    def should_allow_new_position(self, current_position_count: int) -> Tuple[bool, str]:
        """
        Check if a new position should be allowed
        
        Returns:
            (allowed: bool, reason: str)
        """
        if current_position_count >= self.max_positions:
            return False, f"Position limit reached ({current_position_count}/{self.max_positions})"
        
        return True, "OK"
    
    def get_position_quality_report(self, positions: List[Dict]) -> Dict:
        """Generate a quality report on current positions"""
        if not positions:
            return {
                'total_positions': 0,
                'under_limit': True,
                'avg_health_score': 0,
                'healthiest': None,
                'unhealthiest': None
            }
        
        health_scores = []
        for pos in positions:
            health = self.score_position_health(
                symbol=pos['symbol'],
                entry_time=pos.get('entry_time', datetime.now()),
                current_pnl_pct=pos.get('pnl_pct', 0)
            )
            health_scores.append(health)
        
        avg_score = sum(h.score for h in health_scores) / len(health_scores)
        healthiest = max(health_scores, key=lambda h: h.score)
        unhealthiest = min(health_scores, key=lambda h: h.score)
        
        return {
            'total_positions': len(positions),
            'max_allowed': self.max_positions,
            'under_limit': len(positions) <= self.max_positions,
            'avg_health_score': avg_score,
            'healthiest': {
                'symbol': healthiest.symbol,
                'score': healthiest.score,
                'pnl_pct': healthiest.current_pnl_pct * 100
            },
            'unhealthiest': {
                'symbol': unhealthiest.symbol,
                'score': unhealthiest.score,
                'pnl_pct': unhealthiest.current_pnl_pct * 100,
                'reason': unhealthiest.reason
            }
        }


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize with strict limits
    engine = DustPreventionEngine(
        max_positions=5,
        stagnation_hours=4.0,
        min_pnl_movement=0.002
    )
    
    # Mock positions
    positions = [
        {'symbol': 'BTC-USD', 'entry_time': datetime.now() - timedelta(hours=2), 'pnl_pct': 0.025},
        {'symbol': 'ETH-USD', 'entry_time': datetime.now() - timedelta(hours=8), 'pnl_pct': 0.001},
        {'symbol': 'SOL-USD', 'entry_time': datetime.now() - timedelta(hours=6), 'pnl_pct': -0.015},
        {'symbol': 'MATIC-USD', 'entry_time': datetime.now() - timedelta(hours=12), 'pnl_pct': 0.0005},
        {'symbol': 'AVAX-USD', 'entry_time': datetime.now() - timedelta(hours=1), 'pnl_pct': 0.008},
        {'symbol': 'DOT-USD', 'entry_time': datetime.now() - timedelta(hours=10), 'pnl_pct': -0.002},
    ]
    
    # Check positions
    to_close = engine.identify_positions_to_close(positions, force_to_limit=True)
    
    # Log forced exits with profit status transitions
    if to_close:
        print("\n🧹 Executing Forced Exits:")
        for pos_to_close in to_close:
            engine.log_forced_exit(
                symbol=pos_to_close['symbol'],
                reason=pos_to_close['reason'],
                current_pnl_pct=pos_to_close['current_pnl']
            )
    
    # Quality report
    report = engine.get_position_quality_report(positions)
    print(f"\n📊 Position Quality Report:")
    print(f"   Total: {report['total_positions']}/{report['max_allowed']}")
    print(f"   Avg Health Score: {report['avg_health_score']:.1f}/100")
    print(f"   Healthiest: {report['healthiest']['symbol']} (score: {report['healthiest']['score']:.0f})")
    print(f"   Unhealthiest: {report['unhealthiest']['symbol']} (score: {report['unhealthiest']['score']:.0f}, {report['unhealthiest']['reason']})")
