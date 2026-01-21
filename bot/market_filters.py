"""
NIJA Apex Strategy v7.1 - Market Filters Module

Advanced market filtering to avoid low-quality trading conditions:
- Choppy/ranging market detection
- Low-volume filtering
- First seconds of candle filtering
- News event filtering (skeleton for future implementation)
- Spread and slippage checks
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Import scalar helper to prevent tuple comparison crashes
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


def detect_choppy_market(df, adx_threshold=20, atr_threshold_low=0.001):
    """
    Detect choppy/ranging market conditions where trend trading is ineffective.
    
    Choppy market indicators:
    - ADX < 20 (weak trend)
    - Low ATR (low volatility)
    - Price oscillating around moving averages
    
    Args:
        df: DataFrame with OHLCV data and 'adx', 'atr' columns
        adx_threshold: ADX below this value indicates weak trend
        atr_threshold_low: ATR below this percentage indicates too low volatility
    
    Returns:
        dict: {
            'is_choppy': bool,
            'reason': str,
            'adx_value': float,
            'atr_value': float
        }
    """
    if len(df) < 50 or 'adx' not in df.columns or 'atr' not in df.columns:
        return {
            'is_choppy': True,
            'reason': 'Insufficient data for chop detection',
            'adx_value': 0,
            'atr_value': 0
        }
    
    # FIX: Use scalar() to safely extract values (prevents tuple comparison crashes)
    adx_value = scalar(df['adx'].iloc[-1])
    atr_value = scalar(df['atr'].iloc[-1])
    current_price = scalar(df['close'].iloc[-1])
    
    # Calculate ATR as percentage of price
    if current_price > 0:
        atr_pct = atr_value / current_price
    else:
        atr_pct = 0
    
    # Check for choppy conditions
    reasons = []
    
    if adx_value < adx_threshold:
        reasons.append(f'Weak trend (ADX={adx_value:.1f} < {adx_threshold})')
    
    if atr_pct < atr_threshold_low:
        reasons.append(f'Low volatility (ATR={atr_pct*100:.3f}% < {atr_threshold_low*100:.3f}%)')
    
    is_choppy = len(reasons) > 0
    reason = '; '.join(reasons) if reasons else 'Clean trending market'
    
    return {
        'is_choppy': is_choppy,
        'reason': reason,
        'adx_value': adx_value,
        'atr_value': atr_value
    }


def check_minimum_volume(df, min_volume_multiplier=0.5):
    """
    Check if current volume meets minimum threshold for valid trading.
    
    Args:
        df: DataFrame with 'volume' column
        min_volume_multiplier: Minimum volume as multiplier of 20-period average
    
    Returns:
        dict: {
            'volume_sufficient': bool,
            'current_volume': float,
            'avg_volume': float,
            'volume_ratio': float
        }
    """
    if len(df) < 20:
        return {
            'volume_sufficient': False,
            'current_volume': 0,
            'avg_volume': 0,
            'volume_ratio': 0
        }
    
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    
    if avg_volume == 0:
        volume_ratio = 0
        volume_sufficient = False
    else:
        volume_ratio = current_volume / avg_volume
        volume_sufficient = volume_ratio >= min_volume_multiplier
    
    return {
        'volume_sufficient': volume_sufficient,
        'current_volume': current_volume,
        'avg_volume': avg_volume,
        'volume_ratio': volume_ratio
    }


def check_candle_timing(seconds_to_avoid=5):
    """
    Check if we're in the first few seconds of a new candle.
    Avoid trading in first seconds to prevent false signals from incomplete candles.
    
    Args:
        seconds_to_avoid: Number of seconds to avoid at candle start
    
    Returns:
        dict: {
            'can_trade': bool,
            'seconds_into_candle': int,
            'reason': str
        }
    """
    now = datetime.utcnow()
    
    # For 5-minute candles
    seconds_into_candle = (now.minute % 5) * 60 + now.second
    
    can_trade = seconds_into_candle >= seconds_to_avoid
    
    if can_trade:
        reason = f'Safe to trade ({seconds_into_candle}s into 5m candle)'
    else:
        reason = f'Too early in candle ({seconds_into_candle}s < {seconds_to_avoid}s threshold)'
    
    return {
        'can_trade': can_trade,
        'seconds_into_candle': seconds_into_candle,
        'reason': reason
    }


def check_spread_quality(bid_price, ask_price, max_spread_pct=0.001):
    """
    Check if bid-ask spread is acceptable for trading.
    Wide spreads indicate low liquidity or high slippage risk.
    
    Args:
        bid_price: Current bid price
        ask_price: Current ask price
        max_spread_pct: Maximum acceptable spread as percentage (default: 0.1%)
    
    Returns:
        dict: {
            'spread_acceptable': bool,
            'spread_pct': float,
            'spread_absolute': float
        }
    """
    if bid_price <= 0 or ask_price <= 0:
        return {
            'spread_acceptable': False,
            'spread_pct': 0,
            'spread_absolute': 0
        }
    
    mid_price = (bid_price + ask_price) / 2
    spread_absolute = ask_price - bid_price
    
    if mid_price > 0:
        spread_pct = spread_absolute / mid_price
    else:
        spread_pct = 0
    
    spread_acceptable = spread_pct <= max_spread_pct
    
    return {
        'spread_acceptable': spread_acceptable,
        'spread_pct': spread_pct,
        'spread_absolute': spread_absolute
    }


class NewsEventFilter:
    """
    News event filtering system (skeleton for future implementation).
    
    In production, this would integrate with:
    - Economic calendar APIs (e.g., Trading Economics, Forex Factory)
    - News sentiment APIs
    - Custom news detection logic
    
    For now, provides a basic time-based cooldown mechanism.
    """
    
    def __init__(self, cooldown_minutes=3):
        """
        Initialize news filter.
        
        Args:
            cooldown_minutes: Minutes to avoid trading after major news
        """
        self.cooldown_minutes = cooldown_minutes
        self.last_news_events = []  # List of (timestamp, event_type) tuples
    
    def register_news_event(self, event_type='MANUAL', timestamp=None):
        """
        Register a news event manually.
        
        Args:
            event_type: Type of news event (e.g., 'FED', 'EARNINGS', 'MANUAL')
            timestamp: Event timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        self.last_news_events.append((timestamp, event_type))
        
        # Keep only recent events (last hour)
        cutoff = datetime.utcnow() - timedelta(hours=1)
        self.last_news_events = [
            (ts, evt) for ts, evt in self.last_news_events
            if ts > cutoff
        ]
    
    def can_trade(self):
        """
        Check if trading is allowed based on news events.
        
        Returns:
            dict: {
                'can_trade': bool,
                'reason': str,
                'recent_events': list
            }
        """
        if not self.last_news_events:
            return {
                'can_trade': True,
                'reason': 'No recent news events',
                'recent_events': []
            }
        
        now = datetime.utcnow()
        cooldown_delta = timedelta(minutes=self.cooldown_minutes)
        
        # Check for events within cooldown period
        recent_blocking_events = []
        for timestamp, event_type in self.last_news_events:
            if now - timestamp < cooldown_delta:
                recent_blocking_events.append({
                    'type': event_type,
                    'minutes_ago': int((now - timestamp).total_seconds() / 60),
                    'timestamp': timestamp.isoformat()
                })
        
        if recent_blocking_events:
            return {
                'can_trade': False,
                'reason': f'{len(recent_blocking_events)} event(s) within {self.cooldown_minutes}m cooldown',
                'recent_events': recent_blocking_events
            }
        
        return {
            'can_trade': True,
            'reason': 'News cooldown period passed',
            'recent_events': []
        }
    
    def check_scheduled_news(self, current_time=None):
        """
        Check for scheduled news events (skeleton for future API integration).
        
        In production, this would query economic calendar APIs for:
        - FOMC meetings
        - NFP (Non-Farm Payroll) releases
        - CPI/inflation data
        - Major earnings reports
        
        Args:
            current_time: Time to check (default: now)
        
        Returns:
            dict: {
                'has_upcoming_news': bool,
                'minutes_until_news': int,
                'events': list
            }
        """
        # Placeholder implementation
        # TODO: Integrate with economic calendar API
        
        return {
            'has_upcoming_news': False,
            'minutes_until_news': None,
            'events': []
        }


def apply_all_filters(df, adx_threshold=20, min_volume_multiplier=0.5,
                     seconds_to_avoid=5, news_filter=None):
    """
    Apply all market filters and return comprehensive assessment.
    
    Args:
        df: DataFrame with OHLCV data and indicators
        adx_threshold: ADX threshold for chop detection
        min_volume_multiplier: Minimum volume multiplier
        seconds_to_avoid: Seconds to avoid at candle start
        news_filter: Optional NewsEventFilter instance
    
    Returns:
        dict: {
            'can_trade': bool,
            'filters_passed': list,
            'filters_failed': list,
            'details': dict
        }
    """
    filters_passed = []
    filters_failed = []
    details = {}
    
    # Check for choppy market
    chop_result = detect_choppy_market(df, adx_threshold=adx_threshold)
    details['chop_check'] = chop_result
    if not chop_result['is_choppy']:
        filters_passed.append('Clean trending market')
    else:
        filters_failed.append(f"Choppy market: {chop_result['reason']}")
    
    # Check minimum volume
    volume_result = check_minimum_volume(df, min_volume_multiplier=min_volume_multiplier)
    details['volume_check'] = volume_result
    if volume_result['volume_sufficient']:
        filters_passed.append('Sufficient volume')
    else:
        filters_failed.append(f"Low volume: {volume_result['volume_ratio']:.2f}x average")
    
    # Check candle timing
    timing_result = check_candle_timing(seconds_to_avoid=seconds_to_avoid)
    details['timing_check'] = timing_result
    if timing_result['can_trade']:
        filters_passed.append('Good candle timing')
    else:
        filters_failed.append(timing_result['reason'])
    
    # Check news filter if provided
    if news_filter is not None:
        news_result = news_filter.can_trade()
        details['news_check'] = news_result
        if news_result['can_trade']:
            filters_passed.append('No news restrictions')
        else:
            filters_failed.append(f"News cooldown: {news_result['reason']}")
    
    can_trade = len(filters_failed) == 0
    
    return {
        'can_trade': can_trade,
        'filters_passed': filters_passed,
        'filters_failed': filters_failed,
        'details': details
    }


def check_pair_quality(symbol, bid_price, ask_price, volume_24h=None, atr_pct=None,
                       max_spread_pct=0.0015, min_volume_usd=100000, min_atr_pct=0.005,
                       disabled_pairs=None):
    """
    FIX #4: Check if trading pair meets quality standards.
    
    Quality criteria:
    - Spread < 0.15% (tight spreads reduce costs)
    - Volume > $100k daily (adequate liquidity)
    - ATR > 0.5% (sufficient price movement)
    - Not in disabled pairs list
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTC-USD')
        bid_price: Current bid price
        ask_price: Current ask price
        volume_24h: 24-hour volume in USD (optional)
        atr_pct: ATR as percentage of price (optional)
        max_spread_pct: Maximum acceptable spread (default: 0.15%)
        min_volume_usd: Minimum 24h volume in USD (default: $100k)
        min_atr_pct: Minimum ATR percentage (default: 0.5%)
        disabled_pairs: List of disabled pair symbols (default: None)
    
    Returns:
        dict: {
            'quality_acceptable': bool,
            'reasons_passed': list,
            'reasons_failed': list,
            'spread_pct': float,
            'volume_24h': float,
            'atr_pct': float
        }
    """
    if disabled_pairs is None:
        disabled_pairs = []
    
    reasons_passed = []
    reasons_failed = []
    
    # Check if pair is disabled/blacklisted
    if symbol in disabled_pairs:
        reasons_failed.append(f'Pair {symbol} is blacklisted/disabled')
        return {
            'quality_acceptable': False,
            'reasons_passed': reasons_passed,
            'reasons_failed': reasons_failed,
            'spread_pct': 0,
            'volume_24h': 0,
            'atr_pct': 0
        }
    
    # Check spread quality
    spread_result = check_spread_quality(bid_price, ask_price, max_spread_pct)
    spread_pct = spread_result.get('spread_pct', 0)
    
    if spread_result['spread_acceptable']:
        reasons_passed.append(f'Tight spread ({spread_pct*100:.3f}% < {max_spread_pct*100:.2f}%)')
    else:
        reasons_failed.append(f'Wide spread ({spread_pct*100:.3f}% > {max_spread_pct*100:.2f}%)')
    
    # Check volume if provided
    if volume_24h is not None:
        if volume_24h >= min_volume_usd:
            reasons_passed.append(f'Good volume (${volume_24h:,.0f} > ${min_volume_usd:,.0f})')
        else:
            reasons_failed.append(f'Low volume (${volume_24h:,.0f} < ${min_volume_usd:,.0f})')
    
    # Check ATR if provided
    if atr_pct is not None:
        if atr_pct >= min_atr_pct:
            reasons_passed.append(f'Good volatility (ATR {atr_pct*100:.2f}% > {min_atr_pct*100:.2f}%)')
        else:
            reasons_failed.append(f'Low volatility (ATR {atr_pct*100:.2f}% < {min_atr_pct*100:.2f}%)')
    
    quality_acceptable = len(reasons_failed) == 0
    
    return {
        'quality_acceptable': quality_acceptable,
        'reasons_passed': reasons_passed,
        'reasons_failed': reasons_failed,
        'spread_pct': spread_pct,
        'volume_24h': volume_24h or 0,
        'atr_pct': atr_pct or 0
    }
