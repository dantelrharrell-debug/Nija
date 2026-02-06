"""
NIJA Trade Quality Gate - Layer 2 Enhancement
==============================================

Wraps strategy analysis to filter out poor-quality trades.
Different architecture from standard validators - acts as a quality gate.

Key Innovations:
1. Reward-to-risk assessment (not standard R-multiple)
2. Market momentum verification (not standard confirmation)
3. Stop quality scoring (not standard placement check)
"""

import logging
from typing import Dict, Any, Optional
import pandas as pd

logger = logging.getLogger("nija.quality_gate")


def compute_reward_risk_ratio(entry: float, exit_loss: float, exit_profit: float) -> float:
    """Calculate how much profit vs risk (higher is better)"""
    risk_amount = abs(entry - exit_loss)
    reward_amount = abs(exit_profit - entry)
    return reward_amount / risk_amount if risk_amount > 0 else 0.0


def measure_momentum_strength(price_data: pd.DataFrame) -> Dict[str, Any]:
    """Assess if market is moving or stagnant"""
    if len(price_data) < 20:
        return {'strong': False, 'details': 'Insufficient bars'}
    
    recent_volume = price_data['volume'].iloc[-1]
    avg_vol = price_data['volume'].iloc[-20:].mean()
    vol_ratio = recent_volume / avg_vol if avg_vol > 0 else 0
    
    recent_range = price_data['high'].iloc[-1] - price_data['low'].iloc[-1]
    avg_range = (price_data['high'].iloc[-20:] - price_data['low'].iloc[-20:]).mean()
    range_ratio = recent_range / avg_range if avg_range > 0 else 0
    
    is_strong = vol_ratio >= 1.25 or range_ratio >= 1.15
    
    return {
        'strong': is_strong,
        'volume_factor': vol_ratio,
        'range_factor': range_ratio,
        'details': f'Vol:{vol_ratio:.2f}x Range:{range_ratio:.2f}x'
    }


def score_stop_quality(price_data: pd.DataFrame, entry: float, proposed_stop: float, direction: str) -> Dict[str, Any]:
    """Score stop placement quality (0-100)"""
    if 'atr' not in price_data.columns or len(price_data) == 0:
        return {'score': 50, 'quality': 'unknown', 'reason': 'No ATR data'}
    
    atr_val = float(price_data['atr'].iloc[-1])
    stop_distance = abs(entry - proposed_stop)
    stop_in_atr_units = stop_distance / atr_val if atr_val > 0 else 0
    
    # Score based on ATR multiplier
    if stop_in_atr_units < 0.8:
        score = 20  # Too tight, in noise
        quality = 'poor'
        reason = f'Stop too tight ({stop_in_atr_units:.2f}x ATR)'
    elif stop_in_atr_units < 1.0:
        score = 50  # Barely acceptable
        quality = 'marginal'
        reason = f'Stop borderline ({stop_in_atr_units:.2f}x ATR)'
    elif stop_in_atr_units <= 1.5:
        score = 85  # Good placement
        quality = 'good'
        reason = f'Stop well-placed ({stop_in_atr_units:.2f}x ATR)'
    elif stop_in_atr_units <= 2.5:
        score = 75  # Acceptable but wide
        quality = 'acceptable'
        reason = f'Stop wide but ok ({stop_in_atr_units:.2f}x ATR)'
    else:
        score = 40  # Too wide, poor R:R
        quality = 'poor'
        reason = f'Stop too wide ({stop_in_atr_units:.2f}x ATR)'
    
    return {'score': score, 'quality': quality, 'reason': reason, 'atr_multiple': stop_in_atr_units}


class TradeQualityGate:
    """
    Quality gate for filtering trades based on profitability potential.
    
    Unlike standard validators, this uses a scoring approach:
    - Minimum reward/risk ratio: 1.5 (configurable to 2.0)
    - Momentum strength check
    - Stop placement quality score
    """
    
    def __init__(self, min_reward_risk: float = 1.5, require_momentum: bool = True):
        self.min_reward_risk = min_reward_risk
        self.require_momentum = require_momentum
        logger.info(f"✅ Trade Quality Gate active (min R:R = {min_reward_risk})")
    
    def assess_trade_quality(
        self,
        market_data: pd.DataFrame,
        entry_price: float,
        stop_price: float,
        target_price: float,
        trade_direction: str
    ) -> Dict[str, Any]:
        """
        Assess overall trade quality.
        
        Returns dict with:
        - approved: bool
        - reward_risk: float
        - momentum: dict
        - stop_quality: dict
        - rejection_reason: str (if rejected)
        """
        assessment = {
            'approved': True,
            'reward_risk': 0.0,
            'momentum': {},
            'stop_quality': {},
            'rejection_reason': None
        }
        
        # Check 1: Reward/Risk ratio
        rr_ratio = compute_reward_risk_ratio(entry_price, stop_price, target_price)
        assessment['reward_risk'] = rr_ratio
        
        if rr_ratio < self.min_reward_risk:
            assessment['approved'] = False
            assessment['rejection_reason'] = f'Poor R:R {rr_ratio:.2f} < {self.min_reward_risk}'
            return assessment
        
        # Check 2: Momentum strength
        if self.require_momentum:
            momentum_check = measure_momentum_strength(market_data)
            assessment['momentum'] = momentum_check
            
            if not momentum_check['strong']:
                assessment['approved'] = False
                assessment['rejection_reason'] = f"Weak momentum: {momentum_check['details']}"
                return assessment
        
        # Check 3: Stop quality
        stop_eval = score_stop_quality(market_data, entry_price, stop_price, trade_direction)
        assessment['stop_quality'] = stop_eval
        
        if stop_eval['score'] < 40:
            assessment['approved'] = False
            assessment['rejection_reason'] = f"Poor stop: {stop_eval['reason']}"
            return assessment
        
        # All checks passed
        return assessment
    
    def filter_strategy_signal(self, strategy_result: Dict, market_data: pd.DataFrame) -> Dict:
        """
        Filter a strategy signal through quality gate.
        
        Args:
            strategy_result: Original strategy output
            market_data: Price DataFrame
        
        Returns:
            Modified result (hold if rejected, original if approved)
        """
        action = strategy_result.get('action', 'hold')
        
        if action not in ['enter_long', 'enter_short']:
            return strategy_result  # Pass through non-entry signals
        
        # Extract trade parameters
        entry = strategy_result.get('entry_price', 0)
        stop = strategy_result.get('stop_loss', 0)
        
        # Get first target price
        targets = strategy_result.get('take_profit', [])
        if isinstance(targets, list) and len(targets) > 0:
            target = targets[0]
        else:
            target = targets if targets else 0
        
        if entry == 0 or stop == 0 or target == 0:
            return strategy_result  # Can't assess, pass through
        
        # Assess quality
        direction = 'long' if action == 'enter_long' else 'short'
        quality_check = self.assess_trade_quality(
            market_data, entry, stop, target, direction
        )
        
        if not quality_check['approved']:
            # Reject trade
            logger.info(f"   🚫 Quality Gate REJECTED: {quality_check['rejection_reason']}")
            return {
                'action': 'hold',
                'reason': f"Quality gate: {quality_check['rejection_reason']}"
            }
        
        # Approve trade - log quality metrics
        logger.info(f"   ✅ Quality Gate APPROVED: R:R={quality_check['reward_risk']:.2f}")
        if quality_check.get('momentum'):
            logger.info(f"      Momentum: {quality_check['momentum']['details']}")
        if quality_check.get('stop_quality'):
            logger.info(f"      Stop: {quality_check['stop_quality']['reason']}")
        
        return strategy_result
