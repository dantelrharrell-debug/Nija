"""
DUST PREVENTION ENGINE
======================
Requirement B: Kill dust accumulation

Prevents "own a little of everything" by enforcing:
1. Position caps (hard limits on concurrent positions)
2. Asset ranking (only trade the BEST opportunities)
3. Forced exits on stagnation (close positions that aren't moving)

Philosophy: "Own a few things with intention" not "spray and pray"

Enhanced with Position Score Telemetry and Cleanup Metrics (Feb 8, 2026)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Import telemetry and metrics tracking (Enhancement #2 and #3)
try:
    from bot.position_score_telemetry import get_position_telemetry
    TELEMETRY_AVAILABLE = True
    logger.info("✅ Position Score Telemetry loaded")
except ImportError:
    try:
        from position_score_telemetry import get_position_telemetry
        TELEMETRY_AVAILABLE = True
        logger.info("✅ Position Score Telemetry loaded")
    except ImportError:
        TELEMETRY_AVAILABLE = False
        logger.warning("⚠️ Position Score Telemetry not available")
        get_position_telemetry = None

try:
    from bot.cleanup_metrics_tracker import get_cleanup_metrics_tracker
    CLEANUP_METRICS_AVAILABLE = True
    logger.info("✅ Cleanup Metrics Tracker loaded")
except ImportError:
    try:
        from cleanup_metrics_tracker import get_cleanup_metrics_tracker
        CLEANUP_METRICS_AVAILABLE = True
        logger.info("✅ Cleanup Metrics Tracker loaded")
    except ImportError:
        CLEANUP_METRICS_AVAILABLE = False
        logger.warning("⚠️ Cleanup Metrics Tracker not available")
        get_cleanup_metrics_tracker = None


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
    - Auto-closing dust positions (< $1 USD)
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
    
    # Dust threshold (USD value)
    DUST_THRESHOLD_USD = 1.00  # Positions below $1 USD are considered dust
    
    def __init__(self, 
                 max_positions: int = 5,
                 stagnation_hours: float = 4.0,
                 min_pnl_movement: float = 0.002,
                 auto_dust_cleanup_enabled: bool = True,
                 dust_threshold_usd: float = 1.00,
                 enable_telemetry: bool = True,
                 enable_cleanup_metrics: bool = True):
        """
        Args:
            max_positions: Maximum concurrent positions (default: 5 for quality focus)
            stagnation_hours: Hours without P&L movement before forced exit
            min_pnl_movement: Minimum P&L% change to consider "movement" (0.2%)
            auto_dust_cleanup_enabled: Enable automatic cleanup of dust positions
            dust_threshold_usd: USD value threshold for dust positions (default: $1.00)
            enable_telemetry: Enable position score telemetry tracking (Enhancement #2)
            enable_cleanup_metrics: Enable cleanup metrics tracking (Enhancement #3)
        """
        self.max_positions = max_positions
        self.stagnation_hours = stagnation_hours
        self.min_pnl_movement = min_pnl_movement
        self.auto_dust_cleanup_enabled = auto_dust_cleanup_enabled
        self.dust_threshold_usd = dust_threshold_usd
        
        # Track P&L movement over time
        self.position_history: Dict[str, List[Tuple[datetime, float]]] = {}
        
        # Initialize telemetry (Enhancement #2)
        self.telemetry_enabled = enable_telemetry and TELEMETRY_AVAILABLE
        if self.telemetry_enabled:
            self.telemetry = get_position_telemetry()
            logger.info("   Position Score Telemetry: ENABLED")
        else:
            self.telemetry = None
            
        # Initialize cleanup metrics (Enhancement #3)
        self.metrics_enabled = enable_cleanup_metrics and CLEANUP_METRICS_AVAILABLE
        if self.metrics_enabled:
            self.metrics = get_cleanup_metrics_tracker()
            logger.info("   Cleanup Metrics Tracking: ENABLED")
        else:
            self.metrics = None
        
        logger.info(f"🧹 DustPreventionEngine initialized:")
        logger.info(f"   Max Positions: {max_positions} (QUALITY > QUANTITY)")
        logger.info(f"   Stagnation Limit: {stagnation_hours}h")
        logger.info(f"   Min Movement: {min_pnl_movement*100:.2f}%")
        logger.info(f"   Auto Dust Cleanup: {'ENABLED' if auto_dust_cleanup_enabled else 'DISABLED'}")
        logger.info(f"   Dust Threshold: ${dust_threshold_usd:.2f} USD")
    
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
                              current_pnl_pct: float,
                              size_usd: float = 0.0) -> PositionHealth:
        """
        Score a position's health (0-100, higher = keep, lower = exit)
        
        Scoring factors:
        - P&L performance (most important)
        - Movement vs stagnation
        - Age (older positions scored lower)
        
        Args:
            symbol: Trading symbol
            entry_time: Position entry time
            current_pnl_pct: Current P&L percentage
            size_usd: Position size in USD (optional, for telemetry)
        
        Returns:
            PositionHealth object with score and reason
        """
        now = datetime.now()
        age_hours = (now - entry_time).total_seconds() / 3600
        stagnation_hours = self.get_hours_since_last_movement(symbol)
        
        score = 50.0  # Neutral baseline
        reasons = []
        
        # Track score contributions for telemetry
        pnl_contribution = 0.0
        stagnation_contribution = 0.0
        age_contribution = 0.0
        
        # Factor 1: P&L Performance (±30 points)
        if current_pnl_pct > self.PNL_STRONG_PROFIT_THRESHOLD:
            pnl_contribution = 30
            score += pnl_contribution
            reasons.append("strong profit")
        elif current_pnl_pct > self.PNL_PROFIT_THRESHOLD:
            pnl_contribution = 15
            score += pnl_contribution
            reasons.append("profitable")
        elif current_pnl_pct < self.PNL_STRONG_LOSS_THRESHOLD:
            pnl_contribution = -30
            score += pnl_contribution
            reasons.append("strong loss")
        elif current_pnl_pct < self.PNL_LOSS_THRESHOLD:
            pnl_contribution = -15
            score += pnl_contribution
            reasons.append("losing")
        else:
            reasons.append("flat P&L")
        
        # Factor 2: Stagnation (±25 points)
        if stagnation_hours > self.stagnation_hours:
            stagnation_contribution = -25
            score += stagnation_contribution
            reasons.append(f"stagnant {stagnation_hours:.1f}h")
        elif stagnation_hours < 0.5:
            stagnation_contribution = 10
            score += stagnation_contribution
            reasons.append("active movement")
        
        # Factor 3: Age (±15 points) - prefer younger positions
        if age_hours > self.AGE_OLD_HOURS:
            age_contribution = -15
            score += age_contribution
            reasons.append(f"old {age_hours:.1f}h")
        elif age_hours > self.AGE_AGING_HOURS:
            age_contribution = -5
            score += age_contribution
            reasons.append(f"aging {age_hours:.1f}h")
        elif age_hours < self.AGE_FRESH_HOURS:
            age_contribution = 5
            score += age_contribution
            reasons.append("fresh")
        
        # Factor 4: Stale losers get worst score
        if current_pnl_pct < 0 and stagnation_hours > self.stagnation_hours / 2:
            penalty = -20
            score += penalty
            reasons.append("STALE LOSER")
        
        reason = ", ".join(reasons)
        final_score = max(0, min(100, score))  # Clamp 0-100
        
        # Record telemetry (Enhancement #2)
        if self.telemetry_enabled and self.telemetry:
            # Determine health status
            if final_score >= 70:
                health_status = "excellent"
            elif final_score >= 50:
                health_status = "good"
            elif final_score >= 30:
                health_status = "fair"
            else:
                health_status = "unhealthy"
            
            self.telemetry.record_position_score(
                symbol=symbol,
                score=final_score,
                pnl_pct=current_pnl_pct,
                age_hours=age_hours,
                stagnation_hours=stagnation_hours,
                pnl_contribution=pnl_contribution,
                stagnation_contribution=stagnation_contribution,
                age_contribution=age_contribution,
                survived_pruning=True,  # Will be updated if position is pruned
                health_status=health_status,
                size_usd=size_usd,
                entry_time=entry_time
            )
        
        return PositionHealth(
            symbol=symbol,
            entry_time=entry_time,
            current_pnl_pct=current_pnl_pct,
            age_hours=age_hours,
            last_movement_hours=stagnation_hours,
            score=final_score,
            reason=reason
        )
    
    def identify_positions_to_close(self,
                                     positions: List[Dict],
                                     force_to_limit: bool = True) -> List[Dict]:
        """
        Identify which positions should be closed
        
        Args:
            positions: List of position dicts with 'symbol', 'entry_time', 'pnl_pct', 'size_usd'
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
            
            # Get position size
            size_usd = pos.get('size_usd', 0)
            
            # Score health
            health = self.score_position_health(
                symbol=pos['symbol'],
                entry_time=pos.get('entry_time', datetime.now()),
                current_pnl_pct=pos.get('pnl_pct', 0),
                size_usd=size_usd
            )
            health_scores.append((pos, health))
            
            # Track position size for metrics (Enhancement #3)
            if self.metrics_enabled and self.metrics and size_usd > 0:
                self.metrics.track_position_size(size_usd)
        
        # Sort by health score (lowest first = worst positions first)
        health_scores.sort(key=lambda x: x[1].score)
        
        to_close = []
        symbols_to_close = set()  # Track symbols for O(1) lookup
        
        # Rule 0: Auto-close dust positions (if enabled)
        if self.auto_dust_cleanup_enabled:
            for pos, health in health_scores:
                size_usd = pos.get('size_usd', 0)
                if size_usd > 0 and size_usd < self.dust_threshold_usd:
                    pnl_pct = pos.get('pnl_pct', 0)
                    age_hours = health.age_hours
                    
                    to_close.append({
                        'symbol': pos['symbol'],
                        'reason': f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})',
                        'health_score': health.score,
                        'priority': 'HIGH',
                        'profit_status_transition': 'PENDING → CONFIRMED',
                        'current_pnl': pnl_pct,
                        'size_usd': size_usd,
                        'cleanup_type': 'DUST'
                    })
                    symbols_to_close.add(pos['symbol'])
                    
                    # Record cleanup metrics (Enhancement #3)
                    if self.metrics_enabled and self.metrics:
                        self.metrics.record_cleanup(
                            symbol=pos['symbol'],
                            cleanup_type='DUST',
                            size_usd=size_usd,
                            pnl_pct=pnl_pct,
                            age_hours=age_hours,
                            reason=f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})'
                        )
                    
                    # Record telemetry (Enhancement #2)
                    if self.telemetry_enabled and self.telemetry:
                        self.telemetry.record_pruning_event(
                            symbol=pos['symbol'],
                            reason=f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})',
                            cleanup_type='DUST',
                            final_score=health.score,
                            final_pnl_pct=pnl_pct,
                            size_usd=size_usd,
                            age_hours=age_hours
                        )
        
        # Rule 1: Force close if over position limit
        if force_to_limit and len(positions) > self.max_positions:
            excess = len(positions) - self.max_positions
            logger.warning(f"🧹 DUST CLEANUP: {len(positions)} positions exceeds limit of {self.max_positions}")
            logger.warning(f"   Forcing exit of {excess} worst positions")
            
            for i in range(excess):
                pos, health = health_scores[i]
                # Skip if already marked for dust cleanup (O(1) lookup)
                if pos['symbol'] in symbols_to_close:
                    continue
                    
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Position cap exceeded (score: {health.score:.0f}, {health.reason})',
                    'health_score': health.score,
                    'priority': 'HIGH',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pos.get('pnl_pct', 0),
                    'cleanup_type': 'CAP_EXCEEDED'
                })
                symbols_to_close.add(pos['symbol'])
                
                # Record cleanup metrics (Enhancement #3)
                if self.metrics_enabled and self.metrics:
                    self.metrics.record_cleanup(
                        symbol=pos['symbol'],
                        cleanup_type='CAP_EXCEEDED',
                        size_usd=pos.get('size_usd', 0),
                        pnl_pct=pos.get('pnl_pct', 0),
                        age_hours=health.age_hours,
                        reason=f'Position cap exceeded (score: {health.score:.0f}, {health.reason})'
                    )
                
                # Record telemetry (Enhancement #2)
                if self.telemetry_enabled and self.telemetry:
                    self.telemetry.record_pruning_event(
                        symbol=pos['symbol'],
                        reason=f'Position cap exceeded (score: {health.score:.0f}, {health.reason})',
                        cleanup_type='CAP_EXCEEDED',
                        final_score=health.score,
                        final_pnl_pct=pos.get('pnl_pct', 0),
                        size_usd=pos.get('size_usd', 0),
                        age_hours=health.age_hours
                    )
        
        # Rule 2: Close stagnant positions (score < 30)
        for pos, health in health_scores:
            # Skip if already marked for closure (O(1) lookup)
            if pos['symbol'] in symbols_to_close:
                continue
            
            pnl_pct = pos.get('pnl_pct', 0)
            size_usd = pos.get('size_usd', 0)
            
            if health.score < 30:
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Unhealthy position (score: {health.score:.0f}, {health.reason})',
                    'health_score': health.score,
                    'priority': 'MEDIUM',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pnl_pct,
                    'cleanup_type': 'UNHEALTHY'
                })
                symbols_to_close.add(pos['symbol'])
                
                # Record cleanup metrics (Enhancement #3)
                if self.metrics_enabled and self.metrics:
                    self.metrics.record_cleanup(
                        symbol=pos['symbol'],
                        cleanup_type='UNHEALTHY',
                        size_usd=size_usd,
                        pnl_pct=pnl_pct,
                        age_hours=health.age_hours,
                        reason=f'Unhealthy position (score: {health.score:.0f}, {health.reason})'
                    )
                
                # Record telemetry (Enhancement #2)
                if self.telemetry_enabled and self.telemetry:
                    self.telemetry.record_pruning_event(
                        symbol=pos['symbol'],
                        reason=f'Unhealthy position (score: {health.score:.0f}, {health.reason})',
                        cleanup_type='UNHEALTHY',
                        final_score=health.score,
                        final_pnl_pct=pnl_pct,
                        size_usd=size_usd,
                        age_hours=health.age_hours
                    )
            elif health.last_movement_hours > self.stagnation_hours:
                to_close.append({
                    'symbol': pos['symbol'],
                    'reason': f'Stagnant (no movement for {health.last_movement_hours:.1f}h)',
                    'health_score': health.score,
                    'priority': 'MEDIUM',
                    'profit_status_transition': 'PENDING → CONFIRMED',
                    'current_pnl': pnl_pct,
                    'cleanup_type': 'STAGNANT'
                })
                symbols_to_close.add(pos['symbol'])
                
                # Record cleanup metrics (Enhancement #3)
                if self.metrics_enabled and self.metrics:
                    self.metrics.record_cleanup(
                        symbol=pos['symbol'],
                        cleanup_type='STAGNANT',
                        size_usd=size_usd,
                        pnl_pct=pnl_pct,
                        age_hours=health.age_hours,
                        reason=f'Stagnant (no movement for {health.last_movement_hours:.1f}h)'
                    )
                
                # Record telemetry (Enhancement #2)
                if self.telemetry_enabled and self.telemetry:
                    self.telemetry.record_pruning_event(
                        symbol=pos['symbol'],
                        reason=f'Stagnant (no movement for {health.last_movement_hours:.1f}h)',
                        cleanup_type='STAGNANT',
                        final_score=health.score,
                        final_pnl_pct=pnl_pct,
                        size_usd=size_usd,
                        age_hours=health.age_hours
                    )
        
        # Log results with profit status transitions
        if to_close:
            logger.warning(f"🧹 Identified {len(to_close)} positions for cleanup:")
            for tc in to_close:
                cleanup_tag = f"[{tc.get('cleanup_type', 'UNKNOWN')}]"
                logger.warning(f"   {tc['priority']} {cleanup_tag}: {tc['symbol']} - {tc['reason']}")
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
    
    def identify_dust_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify positions that are below the dust threshold
        
        Args:
            positions: List of position dicts with 'symbol', 'size_usd'
        
        Returns:
            List of dust positions with details
        """
        if not self.auto_dust_cleanup_enabled:
            return []
        
        dust_positions = []
        for pos in positions:
            size_usd = pos.get('size_usd', 0)
            if size_usd > 0 and size_usd < self.dust_threshold_usd:
                dust_positions.append({
                    'symbol': pos['symbol'],
                    'size_usd': size_usd,
                    'reason': f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})',
                    'pnl_pct': pos.get('pnl_pct', 0)
                })
        
        if dust_positions:
            logger.info(f"🧹 Found {len(dust_positions)} dust positions:")
            for dp in dust_positions:
                logger.info(f"   {dp['symbol']}: ${dp['size_usd']:.2f} (P&L: {dp['pnl_pct']*100:+.2f}%)")
        
        return dust_positions
    
    def consolidate_dust_positions(self, positions: List[Dict]) -> Tuple[List[Dict], Dict]:
        """
        Consolidate dust positions by identifying them for closure.
        
        This is the primary method for automatic dust consolidation at the execution layer.
        It returns a list of dust positions that should be closed to free up capital.
        
        Args:
            positions: List of all current positions
            
        Returns:
            Tuple[List[Dict], Dict]: (positions_to_close, consolidation_summary)
                - positions_to_close: List of dust positions to close
                - consolidation_summary: Dict with consolidation metrics
        """
        if not self.auto_dust_cleanup_enabled:
            return [], {
                'enabled': False,
                'dust_positions_found': 0,
                'positions_to_close': 0,
                'total_dust_value': 0.0
            }
        
        dust_positions = self.identify_dust_positions(positions)
        
        # All dust positions should be closed
        positions_to_close = []
        total_dust_value = 0.0
        
        for dust_pos in dust_positions:
            positions_to_close.append({
                'symbol': dust_pos['symbol'],
                'size_usd': dust_pos['size_usd'],
                'pnl_pct': dust_pos['pnl_pct'],
                'reason': dust_pos['reason'],
                'priority': 'HIGH',
                'cleanup_type': 'DUST_CONSOLIDATION'
            })
            total_dust_value += dust_pos['size_usd']
        
        consolidation_summary = {
            'enabled': True,
            'dust_positions_found': len(dust_positions),
            'positions_to_close': len(positions_to_close),
            'total_dust_value': total_dust_value,
            'dust_threshold_usd': self.dust_threshold_usd,
            'timestamp': datetime.now().isoformat()
        }
        
        if positions_to_close:
            logger.warning(f"")
            logger.warning(f"🧹 DUST CONSOLIDATION TRIGGERED")
            logger.warning(f"   Found {len(dust_positions)} dust positions totaling ${total_dust_value:.2f}")
            logger.warning(f"   Dust threshold: ${self.dust_threshold_usd:.2f}")
            logger.warning(f"   Action: Close all dust positions to free capital and avoid fee bleed")
            logger.warning(f"")
            
            for pos in positions_to_close:
                logger.warning(f"   📌 {pos['symbol']}: ${pos['size_usd']:.2f} - {pos['reason']}")
        else:
            logger.info(f"✅ No dust positions found (threshold: ${self.dust_threshold_usd:.2f})")
        
        return positions_to_close, consolidation_summary
    
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
