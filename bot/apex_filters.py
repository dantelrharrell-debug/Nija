"""
NIJA Apex Strategy v7.1 - Smart Filters
=========================================

Smart filters to block trading in unfavorable conditions:
- News event blocking (placeholder)
- Low volume filter
- New candle timing filter
- Chop/sideways detection
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Tuple, Optional
from apex_config import SMART_FILTERS
from indicators import scalar


class ApexSmartFilters:
    """
    Smart filters for Apex Strategy v7.1
    """

    def __init__(self):
        """Initialize smart filters"""
        self.last_news_event_time = None
        self.blocked_until = None

    def check_news_blocking(self, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if trading should be blocked due to recent news event

        This is a placeholder implementation. In production, this would
        integrate with a news API or calendar.

        Args:
            current_time: Current time (default: now)

        Returns:
            tuple: (is_blocked, reason)
        """
        if not SMART_FILTERS['news_blocking']['enabled']:
            return False, "News blocking disabled"

        if current_time is None:
            current_time = datetime.now()

        # If we have a blocked_until time set, check if we're still in cooldown
        if self.blocked_until and current_time < self.blocked_until:
            remaining = (self.blocked_until - current_time).total_seconds() / 60
            return True, f"News cooldown active ({remaining:.1f} min remaining)"

        return False, "No news blocking active"

    def register_news_event(self, event_time: Optional[datetime] = None):
        """
        Register a news event and start cooldown period

        Args:
            event_time: Time of news event (default: now)
        """
        if event_time is None:
            event_time = datetime.now()

        cooldown_minutes = SMART_FILTERS['news_blocking']['cooldown_minutes']
        self.last_news_event_time = event_time
        self.blocked_until = event_time + timedelta(minutes=cooldown_minutes)

    def check_low_volume(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Check if current volume is too low for trading

        Args:
            df: DataFrame with volume data

        Returns:
            tuple: (is_blocked, reason)
        """
        if not SMART_FILTERS['low_volume']['enabled']:
            return False, "Low volume filter disabled"

        if len(df) < 20:
            return True, "Insufficient data for volume analysis"

        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(window=20, min_periods=20).mean().iloc[-1]

        threshold = SMART_FILTERS['low_volume']['threshold']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio < threshold:
            return True, f"Volume too low ({volume_ratio:.1%} of average, threshold: {threshold:.0%})"

        return False, f"Volume acceptable ({volume_ratio:.1%} of average)"

    def check_new_candle_timing(
        self,
        candle_open_time: datetime,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Check if we're in the first few seconds of a new candle

        Args:
            candle_open_time: When the current candle opened
            current_time: Current time (default: now)

        Returns:
            tuple: (is_blocked, reason)
        """
        if not SMART_FILTERS['new_candle_timing']['enabled']:
            return False, "New candle timing filter disabled"

        if current_time is None:
            current_time = datetime.now()

        seconds_into_candle = (current_time - candle_open_time).total_seconds()
        block_seconds = SMART_FILTERS['new_candle_timing']['block_first_seconds']

        if seconds_into_candle < block_seconds:
            return True, f"Too early in candle ({seconds_into_candle:.0f}s < {block_seconds}s)"

        return False, f"Candle timing acceptable ({seconds_into_candle:.0f}s into candle)"

    def check_chop_detection(self, adx: float) -> Tuple[bool, str]:
        """
        Check if market is in choppy/sideways condition

        Args:
            adx: ADX value

        Returns:
            tuple: (is_blocked, reason)
        """
        if not SMART_FILTERS['chop_detection']['enabled']:
            return False, "Chop detection disabled"

        threshold = SMART_FILTERS['chop_detection']['adx_threshold']
        adx = scalar(adx)

        if adx < threshold:
            return True, f"Market is choppy (ADX {adx:.1f} < {threshold})"

        return False, f"Market is trending (ADX {adx:.1f} >= {threshold})"

    def check_all_filters(
        self,
        df: pd.DataFrame,
        adx: float,
        candle_open_time: Optional[datetime] = None,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, list]:
        """
        Check all filters at once

        Args:
            df: DataFrame with OHLCV data
            adx: ADX value
            candle_open_time: When current candle opened
            current_time: Current time

        Returns:
            tuple: (any_blocked, list_of_blocking_reasons)
        """
        blocking_reasons = []

        # Check news blocking
        is_blocked, reason = self.check_news_blocking(current_time)
        if is_blocked:
            blocking_reasons.append(f"News: {reason}")

        # Check low volume
        is_blocked, reason = self.check_low_volume(df)
        if is_blocked:
            blocking_reasons.append(f"Volume: {reason}")

        # Check new candle timing
        if candle_open_time:
            is_blocked, reason = self.check_new_candle_timing(candle_open_time, current_time)
            if is_blocked:
                blocking_reasons.append(f"Timing: {reason}")

        # Check chop detection
        is_blocked, reason = self.check_chop_detection(adx)
        if is_blocked:
            blocking_reasons.append(f"Chop: {reason}")

        return len(blocking_reasons) > 0, blocking_reasons

    def get_filter_status(
        self,
        df: pd.DataFrame,
        adx: float,
        candle_open_time: Optional[datetime] = None,
        current_time: Optional[datetime] = None
    ) -> dict:
        """
        Get detailed status of all filters

        Args:
            df: DataFrame with OHLCV data
            adx: ADX value
            candle_open_time: When current candle opened
            current_time: Current time

        Returns:
            dict: Detailed filter status
        """
        news_blocked, news_reason = self.check_news_blocking(current_time)
        volume_blocked, volume_reason = self.check_low_volume(df)
        chop_blocked, chop_reason = self.check_chop_detection(adx)

        timing_blocked = False
        timing_reason = "N/A"
        if candle_open_time:
            timing_blocked, timing_reason = self.check_new_candle_timing(candle_open_time, current_time)

        any_blocked = news_blocked or volume_blocked or timing_blocked or chop_blocked

        return {
            'any_blocked': any_blocked,
            'news': {
                'blocked': news_blocked,
                'reason': news_reason,
            },
            'volume': {
                'blocked': volume_blocked,
                'reason': volume_reason,
            },
            'timing': {
                'blocked': timing_blocked,
                'reason': timing_reason,
            },
            'chop': {
                'blocked': chop_blocked,
                'reason': chop_reason,
            },
        }
