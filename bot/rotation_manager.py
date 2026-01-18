# rotation_manager.py
"""
NIJA Position Rotation Manager - PRO MODE

Enables hedge-fund style position rotation where:
- Open positions count as capital
- Can close weak positions to fund better opportunities
- Never locks all capital (maintains minimum reserve)
- Prioritizes highest probability setups

Version: 1.0 (PRO MODE)
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("nija.rotation_manager")


class RotationManager:
    """
    Manages position rotation decisions for PRO MODE trading.
    
    Enables rotating capital from underperforming positions into better opportunities
    without needing to wait for free USD balance.
    """
    
    def __init__(self, 
                 min_free_balance_pct: float = 0.15,
                 rotation_enabled: bool = True,
                 min_opportunity_improvement: float = 0.20):
        """
        Initialize Rotation Manager.
        
        Args:
            min_free_balance_pct: Minimum % of total capital to keep as free balance (default 15%)
            rotation_enabled: Enable/disable rotation mode (default True)
            min_opportunity_improvement: Minimum improvement % to justify rotation (default 20%)
        """
        self.min_free_balance_pct = min_free_balance_pct
        self.rotation_enabled = rotation_enabled
        self.min_opportunity_improvement = min_opportunity_improvement
        
        # Track rotation statistics
        self.rotations_today = 0
        self.total_rotations = 0
        self.successful_rotations = 0
        
        logger.info("🔄 Rotation Manager initialized - PRO MODE ACTIVE")
        logger.info(f"   Min free balance reserve: {min_free_balance_pct*100:.0f}%")
        logger.info(f"   Min improvement for rotation: {min_opportunity_improvement*100:.0f}%")
    
    def can_rotate(self, total_capital: float, free_balance: float, 
                   current_positions: int) -> Tuple[bool, str]:
        """
        Check if rotation is currently allowed.
        
        Args:
            total_capital: Total capital (free + positions)
            free_balance: Currently available free balance
            current_positions: Number of open positions
        
        Returns:
            Tuple of (can_rotate: bool, reason: str)
        """
        if not self.rotation_enabled:
            return False, "Rotation mode disabled"
        
        if current_positions == 0:
            return False, "No positions to rotate from"
        
        if total_capital <= 0:
            return False, "Invalid total capital"
        
        # Check if we have enough free balance reserve
        free_balance_pct = free_balance / total_capital if total_capital > 0 else 0
        min_required_free = total_capital * self.min_free_balance_pct
        
        # We can rotate if we're below minimum free balance
        # This allows closing positions to free up capital
        if free_balance < min_required_free:
            return True, f"Below minimum free balance reserve ({free_balance_pct*100:.1f}% < {self.min_free_balance_pct*100:.0f}%)"
        
        return True, "Sufficient free balance for rotation"
    
    def score_position_for_rotation(self, position: Dict, 
                                    position_metrics: Optional[Dict] = None) -> float:
        """
        Score a position for rotation priority (higher score = better candidate to close).
        
        Factors considered:
        - Profitability (losing positions first)
        - Time held (stale positions)
        - RSI conditions (overbought/oversold)
        - Position size (smaller positions easier to rotate)
        
        Args:
            position: Position dict with symbol, quantity, etc.
            position_metrics: Optional dict with pnl_pct, age_hours, rsi, etc.
        
        Returns:
            float: Rotation score (0-100, higher = better candidate for closing)
        """
        if not position_metrics:
            position_metrics = {}
        
        score = 50.0  # Neutral baseline
        
        # Factor 1: P&L (most important - close losers first)
        pnl_pct = position_metrics.get('pnl_pct', 0.0)
        if pnl_pct < -5.0:
            score += 30  # Big loser - high priority to close
        elif pnl_pct < -2.0:
            score += 20  # Small loser
        elif pnl_pct < 0:
            score += 10  # Slight loser
        elif pnl_pct > 5.0:
            score -= 30  # Big winner - don't close
        elif pnl_pct > 2.0:
            score -= 20  # Good profit
        
        # Factor 2: Age (close stale positions)
        age_hours = position_metrics.get('age_hours', 0)
        if age_hours > 8:
            score += 15  # Very stale
        elif age_hours > 4:
            score += 10  # Moderately stale
        elif age_hours < 0.5:
            score -= 10  # Very new - give it time
        
        # Factor 3: RSI (overbought = close, oversold = hold)
        rsi = position_metrics.get('rsi', 50)
        if rsi > 70:
            score += 15  # Overbought - good time to exit
        elif rsi < 30:
            score -= 15  # Oversold - might recover
        
        # Factor 4: Position size (smaller = easier to rotate)
        position_value = position_metrics.get('value', 0)
        if position_value < 5:
            score += 10  # Very small position
        elif position_value < 10:
            score += 5  # Small position
        
        # Clamp score to 0-100 range
        score = max(0, min(100, score))
        
        return score
    
    def select_positions_for_rotation(self, positions: List[Dict], 
                                     position_metrics: Dict[str, Dict],
                                     needed_capital: float,
                                     total_capital: float) -> List[Dict]:
        """
        Select which positions to close to free up capital for better opportunities.
        
        Args:
            positions: List of current position dicts
            position_metrics: Dict mapping symbol -> metrics (pnl_pct, age, rsi, etc.)
            needed_capital: Amount of capital needed for new opportunity
            total_capital: Total account capital
        
        Returns:
            List of positions to close (ordered by rotation priority)
        """
        if not positions:
            return []
        
        # Score all positions
        scored_positions = []
        for pos in positions:
            symbol = pos.get('symbol')
            metrics = position_metrics.get(symbol, {})
            score = self.score_position_for_rotation(pos, metrics)
            
            scored_positions.append({
                'position': pos,
                'score': score,
                'value': metrics.get('value', 0),
                'symbol': symbol
            })
        
        # Sort by score (highest first = best candidates to close)
        scored_positions.sort(key=lambda x: x['score'], reverse=True)
        
        # Select positions to close until we have enough capital
        positions_to_close = []
        capital_freed = 0.0
        min_free_reserve = total_capital * self.min_free_balance_pct
        
        for item in scored_positions:
            # Check if we've freed enough capital
            if capital_freed >= needed_capital:
                break
            
            # Don't close positions with very low rotation score (good positions)
            if item['score'] < 40:
                logger.info(f"   ⚠️ Skipping {item['symbol']} - score too low ({item['score']:.1f}/100)")
                continue
            
            positions_to_close.append(item['position'])
            capital_freed += item['value']
            
            logger.info(f"   ✓ Selected {item['symbol']} for rotation (score: {item['score']:.1f}/100, value: ${item['value']:.2f})")
        
        if capital_freed < needed_capital:
            logger.warning(f"⚠️ Could only free ${capital_freed:.2f} of ${needed_capital:.2f} needed")
        else:
            logger.info(f"✅ Selected {len(positions_to_close)} positions to rotate (freeing ${capital_freed:.2f})")
        
        return positions_to_close
    
    def should_rotate_for_opportunity(self, opportunity_quality: float,
                                     current_position_quality: float) -> Tuple[bool, str]:
        """
        Determine if a new opportunity is good enough to justify rotating from current positions.
        
        Args:
            opportunity_quality: Quality score of new opportunity (0-1)
            current_position_quality: Average quality of current positions (0-1)
        
        Returns:
            Tuple of (should_rotate: bool, reason: str)
        """
        if opportunity_quality <= 0 or current_position_quality <= 0:
            return False, "Invalid quality scores (must be > 0)"
        
        # Calculate improvement percentage
        # Safe: current_position_quality is guaranteed > 0 from check above
        improvement = (opportunity_quality - current_position_quality) / current_position_quality
        
        if improvement >= self.min_opportunity_improvement:
            return True, f"New opportunity {improvement*100:.0f}% better than current positions"
        else:
            return False, f"Improvement ({improvement*100:.0f}%) below threshold ({self.min_opportunity_improvement*100:.0f}%)"
    
    def record_rotation(self, success: bool):
        """Record a rotation attempt for statistics."""
        self.total_rotations += 1
        self.rotations_today += 1
        if success:
            self.successful_rotations += 1
    
    def get_rotation_stats(self) -> Dict:
        """Get rotation statistics."""
        success_rate = (self.successful_rotations / self.total_rotations * 100) if self.total_rotations > 0 else 0
        
        return {
            'rotations_today': self.rotations_today,
            'total_rotations': self.total_rotations,
            'successful_rotations': self.successful_rotations,
            'success_rate': success_rate
        }
