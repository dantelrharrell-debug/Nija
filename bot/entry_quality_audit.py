"""
NIJA Entry Quality Audit System

Provides comprehensive entry quality scoring and audit logging for trade entries.
Evaluates multiple factors to determine entry quality and maintain an audit trail.

Features:
- Multi-factor entry scoring (0-100 scale)
- Signal strength evaluation
- Volatility assessment
- Trend alignment scoring
- Volume confirmation
- Comprehensive audit logging

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
import pandas as pd

logger = logging.getLogger("nija.entry_quality_audit")

# Import indicators for quality calculations
try:
    from indicators import calculate_atr, calculate_adx, scalar
except ImportError:
    try:
        from bot.indicators import calculate_atr, calculate_adx, scalar
    except ImportError:
        # Fallback definitions
        def scalar(x):
            if isinstance(x, (tuple, list)):
                return float(x[0]) if len(x) > 0 else 0.0
            return float(x)
        
        def calculate_atr(df, period=14):
            return pd.Series([0.0] * len(df))
        
        def calculate_adx(df, period=14):
            return pd.Series([0.0] * len(df)), pd.Series([0.0] * len(df)), pd.Series([0.0] * len(df))


class EntryQualityScorer:
    """
    Scores entry quality based on multiple technical factors.
    
    Scoring breakdown (0-100):
    - Signal Strength: 0-30 points (RSI divergence, MACD alignment)
    - Trend Alignment: 0-25 points (ADX strength, price vs EMAs)
    - Volatility Context: 0-20 points (ATR normalization, regime fit)
    - Volume Confirmation: 0-15 points (volume vs average)
    - Risk/Reward Setup: 0-10 points (stop distance, target feasibility)
    """
    
    def __init__(self):
        """Initialize the entry quality scorer"""
        self.audit_log = []
        self.min_passing_score = 60  # Minimum score for quality entry
        
    def score_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        signal_type: str,
        rsi_9: float,
        rsi_14: float,
        macd_value: float,
        macd_signal: float,
        adx_value: float,
        current_price: float,
        volume_ratio: float = 1.0,
        stop_distance_pct: float = 2.0,
        target_distance_pct: float = 4.0
    ) -> Dict:
        """
        Calculate comprehensive entry quality score.
        
        Args:
            symbol: Trading pair symbol
            df: OHLCV dataframe
            signal_type: 'LONG' or 'SHORT'
            rsi_9: Fast RSI value
            rsi_14: Slow RSI value
            macd_value: MACD line value
            macd_signal: MACD signal line value
            adx_value: ADX trend strength
            current_price: Current market price
            volume_ratio: Current volume / average volume
            stop_distance_pct: Stop loss distance as percentage
            target_distance_pct: Take profit distance as percentage
            
        Returns:
            Dictionary with score breakdown and audit data
        """
        timestamp = datetime.now()
        
        # 1. Signal Strength Score (0-30)
        signal_score = self._score_signal_strength(
            signal_type, rsi_9, rsi_14, macd_value, macd_signal
        )
        
        # 2. Trend Alignment Score (0-25)
        trend_score = self._score_trend_alignment(
            df, signal_type, adx_value, current_price
        )
        
        # 3. Volatility Context Score (0-20)
        volatility_score = self._score_volatility_context(
            df, current_price, stop_distance_pct
        )
        
        # 4. Volume Confirmation Score (0-15)
        volume_score = self._score_volume_confirmation(volume_ratio)
        
        # 5. Risk/Reward Setup Score (0-10)
        rr_score = self._score_risk_reward(
            stop_distance_pct, target_distance_pct
        )
        
        # Calculate total score
        total_score = signal_score + trend_score + volatility_score + volume_score + rr_score
        
        # Determine quality rating
        quality_rating = self._get_quality_rating(total_score)
        
        # Create audit entry
        audit_entry = {
            'timestamp': timestamp,
            'symbol': symbol,
            'signal_type': signal_type,
            'total_score': total_score,
            'quality_rating': quality_rating,
            'breakdown': {
                'signal_strength': signal_score,
                'trend_alignment': trend_score,
                'volatility_context': volatility_score,
                'volume_confirmation': volume_score,
                'risk_reward_setup': rr_score
            },
            'technical_values': {
                'rsi_9': rsi_9,
                'rsi_14': rsi_14,
                'macd_value': macd_value,
                'macd_signal': macd_signal,
                'adx': adx_value,
                'volume_ratio': volume_ratio,
                'price': current_price,
                'stop_distance_pct': stop_distance_pct,
                'target_distance_pct': target_distance_pct
            },
            'passed': total_score >= self.min_passing_score
        }
        
        # Add to audit log
        self.audit_log.append(audit_entry)
        
        # Log the audit entry
        self._log_audit_entry(audit_entry)
        
        return audit_entry
    
    def _score_signal_strength(
        self,
        signal_type: str,
        rsi_9: float,
        rsi_14: float,
        macd_value: float,
        macd_signal: float
    ) -> float:
        """Score signal strength (0-30 points)"""
        score = 0.0
        
        # RSI alignment (0-15 points)
        if signal_type == 'LONG':
            # For LONG: prefer oversold conditions
            if rsi_14 < 30:
                score += 15  # Perfect oversold
            elif rsi_14 < 40:
                score += 12  # Good oversold
            elif rsi_14 < 50:
                score += 8   # Mild oversold
            elif rsi_14 < 60:
                score += 4   # Neutral
            # RSI divergence bonus
            if rsi_9 < rsi_14:
                score += 5  # Fast RSI showing momentum
        else:  # SHORT
            # For SHORT: prefer overbought conditions
            if rsi_14 > 70:
                score += 15  # Perfect overbought
            elif rsi_14 > 60:
                score += 12  # Good overbought
            elif rsi_14 > 50:
                score += 8   # Mild overbought
            elif rsi_14 > 40:
                score += 4   # Neutral
            # RSI divergence bonus
            if rsi_9 > rsi_14:
                score += 5  # Fast RSI showing momentum
        
        # MACD alignment (0-15 points)
        macd_diff = macd_value - macd_signal
        if signal_type == 'LONG':
            if macd_diff > 0:
                score += min(15, abs(macd_diff) * 10)  # Stronger crossover = more points
        else:  # SHORT
            if macd_diff < 0:
                score += min(15, abs(macd_diff) * 10)
        
        return min(30, score)  # Cap at 30
    
    def _score_trend_alignment(
        self,
        df: pd.DataFrame,
        signal_type: str,
        adx_value: float,
        current_price: float
    ) -> float:
        """Score trend alignment (0-25 points)"""
        score = 0.0
        
        # ADX strength (0-15 points)
        if adx_value >= 40:
            score += 15  # Very strong trend
        elif adx_value >= 30:
            score += 12  # Strong trend
        elif adx_value >= 25:
            score += 9   # Moderate trend
        elif adx_value >= 20:
            score += 6   # Weak trend
        else:
            score += 2   # No clear trend (risky)
        
        # Price position vs moving averages (0-10 points)
        # This would require EMA calculations - simplified here
        # In full implementation, check if price is above/below key EMAs
        if len(df) >= 50:
            # Use recent close prices as proxy for trend
            recent_closes = df['close'].tail(10).values
            price_trend = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
            
            if signal_type == 'LONG' and price_trend > 0:
                score += 10  # Uptrend for LONG
            elif signal_type == 'SHORT' and price_trend < 0:
                score += 10  # Downtrend for SHORT
            else:
                score += 3  # Counter-trend (can work but risky)
        
        return min(25, score)
    
    def _score_volatility_context(
        self,
        df: pd.DataFrame,
        current_price: float,
        stop_distance_pct: float
    ) -> float:
        """Score volatility context (0-20 points)"""
        score = 0.0
        
        # Calculate ATR as percentage of price
        if len(df) >= 14:
            atr = calculate_atr(df, period=14)
            if len(atr) > 0:
                atr_value = scalar(atr.iloc[-1])
                atr_pct = (atr_value / current_price) * 100
                
                # Score based on ATR normalization (0-15 points)
                # Ideal: ATR between 1-3% (moderate volatility)
                if 1.0 <= atr_pct <= 3.0:
                    score += 15  # Ideal volatility
                elif 0.5 <= atr_pct <= 4.0:
                    score += 12  # Good volatility
                elif 0.3 <= atr_pct <= 5.0:
                    score += 8   # Acceptable
                else:
                    score += 3   # Too high or too low
                
                # Stop distance appropriateness (0-5 points)
                # Stop should be 1.5-2.5x ATR
                ideal_stop = atr_pct * 2.0
                stop_ratio = stop_distance_pct / ideal_stop if ideal_stop > 0 else 0
                if 0.8 <= stop_ratio <= 1.5:
                    score += 5  # Well-calibrated stop
                elif 0.5 <= stop_ratio <= 2.0:
                    score += 3  # Acceptable stop
        
        return min(20, score)
    
    def _score_volume_confirmation(self, volume_ratio: float) -> float:
        """Score volume confirmation (0-15 points)"""
        score = 0.0
        
        # Volume should be above average for quality entry
        if volume_ratio >= 2.0:
            score = 15  # High volume confirmation
        elif volume_ratio >= 1.5:
            score = 12  # Good volume
        elif volume_ratio >= 1.2:
            score = 9   # Above average
        elif volume_ratio >= 0.8:
            score = 5   # Average
        else:
            score = 2   # Low volume (risky)
        
        return score
    
    def _score_risk_reward(
        self,
        stop_distance_pct: float,
        target_distance_pct: float
    ) -> float:
        """Score risk/reward setup (0-10 points)"""
        score = 0.0
        
        # Calculate risk/reward ratio
        if stop_distance_pct > 0:
            rr_ratio = target_distance_pct / stop_distance_pct
            
            # Score based on R:R ratio
            if rr_ratio >= 3.0:
                score = 10  # Excellent 3:1 or better
            elif rr_ratio >= 2.5:
                score = 9   # Very good 2.5:1
            elif rr_ratio >= 2.0:
                score = 8   # Good 2:1
            elif rr_ratio >= 1.5:
                score = 6   # Acceptable 1.5:1
            elif rr_ratio >= 1.0:
                score = 3   # Minimum 1:1
            else:
                score = 0   # Poor R:R
        
        return score
    
    def _get_quality_rating(self, score: float) -> str:
        """Get quality rating from score"""
        if score >= 85:
            return "EXCELLENT"
        elif score >= 75:
            return "VERY_GOOD"
        elif score >= 65:
            return "GOOD"
        elif score >= 55:
            return "ACCEPTABLE"
        elif score >= 45:
            return "MARGINAL"
        else:
            return "POOR"
    
    def _log_audit_entry(self, audit_entry: Dict) -> None:
        """Log audit entry for tracking"""
        logger.info(
            f"📊 Entry Quality Audit - {audit_entry['symbol']} {audit_entry['signal_type']}: "
            f"Score={audit_entry['total_score']:.1f}/100 ({audit_entry['quality_rating']}) "
            f"[Signal:{audit_entry['breakdown']['signal_strength']:.0f} "
            f"Trend:{audit_entry['breakdown']['trend_alignment']:.0f} "
            f"Vol:{audit_entry['breakdown']['volatility_context']:.0f} "
            f"Volume:{audit_entry['breakdown']['volume_confirmation']:.0f} "
            f"R/R:{audit_entry['breakdown']['risk_reward_setup']:.0f}] "
            f"{'✅ PASS' if audit_entry['passed'] else '❌ FAIL'}"
        )
    
    def get_audit_log(self, limit: int = 100) -> list:
        """
        Get recent audit log entries.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of audit entries (most recent first)
        """
        return self.audit_log[-limit:][::-1]
    
    def get_statistics(self) -> Dict:
        """
        Get audit statistics.
        
        Returns:
            Dictionary with audit statistics
        """
        if not self.audit_log:
            return {
                'total_entries': 0,
                'passed': 0,
                'failed': 0,
                'pass_rate': 0.0,
                'average_score': 0.0,
                'quality_distribution': {}
            }
        
        total = len(self.audit_log)
        passed = sum(1 for e in self.audit_log if e['passed'])
        failed = total - passed
        
        scores = [e['total_score'] for e in self.audit_log]
        avg_score = sum(scores) / total if total > 0 else 0.0
        
        # Quality distribution
        quality_dist = {}
        for entry in self.audit_log:
            rating = entry['quality_rating']
            quality_dist[rating] = quality_dist.get(rating, 0) + 1
        
        return {
            'total_entries': total,
            'passed': passed,
            'failed': failed,
            'pass_rate': (passed / total * 100) if total > 0 else 0.0,
            'average_score': avg_score,
            'quality_distribution': quality_dist
        }


# Singleton instance
_entry_quality_scorer = None

def get_entry_quality_scorer() -> EntryQualityScorer:
    """Get singleton entry quality scorer instance"""
    global _entry_quality_scorer
    if _entry_quality_scorer is None:
        _entry_quality_scorer = EntryQualityScorer()
    return _entry_quality_scorer
