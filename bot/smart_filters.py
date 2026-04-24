"""
NIJA Smart Filters Module

Advanced filtering logic for trade selection optimization:
- Time-of-day filtering (avoid dead zones, target high-activity periods)
- Volatility regime filtering (more trades in high-vol, avoid chop)
- News event filtering (placeholder hooks for future NLP integration)
- Spread and liquidity checks

These filters help maximize profitability by:
1. Trading when market conditions are most favorable
2. Avoiding low-quality setups
3. Preventing trades during high-risk events
4. Ensuring sufficient liquidity for execution

Author: NIJA Trading Systems
Version: 1.0
Date: December 2024
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger("nija.smart_filters")


class TimeOfDayFilter:
    """
    Filter trades based on time of day to avoid dead zones and target active periods.

    Crypto markets are 24/7, but have distinct activity patterns:
    - US trading hours (9:30 AM - 4:00 PM ET): High activity
    - European trading hours (2:00 AM - 11:00 AM ET): Moderate-high activity
    - Asian trading hours (7:00 PM - 2:00 AM ET): Moderate activity
    - Dead zones (4:00 AM - 7:00 AM ET): Low activity, avoid

    Configurable for different markets and asset classes.
    """

    def __init__(self, timezone: str = "America/New_York"):
        """
        Initialize time-of-day filter.

        Args:
            timezone: Timezone for time-based filtering (default: ET)
        """
        self.timezone = timezone

        # Define trading session windows (24-hour format, ET)
        self.sessions = {
            'us_premarket': (time(4, 0), time(9, 30)),
            'us_regular': (time(9, 30), time(16, 0)),
            'us_afterhours': (time(16, 0), time(20, 0)),
            'asia': (time(19, 0), time(2, 0)),  # Wraps midnight
            'europe': (time(2, 0), time(11, 0)),
            'dead_zone': (time(4, 0), time(7, 0))
        }

        # Activity multipliers for each session (1.0 = normal, >1.0 = more active)
        self.session_activity = {
            'us_premarket': 0.7,
            'us_regular': 1.5,      # Highest activity
            'us_afterhours': 0.8,
            'asia': 0.9,
            'europe': 1.2,
            'dead_zone': 0.3        # Lowest activity - avoid
        }

        logger.info(f"Time-of-day filter initialized (timezone: {timezone})")

    def get_current_session(self, current_time: Optional[datetime] = None) -> str:
        """
        Determine which trading session we're currently in.

        Args:
            current_time: Time to check (default: now)

        Returns:
            str: Session name
        """
        if current_time is None:
            current_time = datetime.now()

        check_time = current_time.time()

        # Check each session
        for session_name, (start, end) in self.sessions.items():
            if session_name == 'asia':
                # Handle wrap around midnight
                if check_time >= start or check_time <= end:
                    return session_name
            else:
                if start <= check_time < end:
                    return session_name

        return 'unknown'

    def should_trade(self, min_activity: float = 0.5,
                    current_time: Optional[datetime] = None) -> Tuple[bool, str, float]:
        """
        Determine if we should trade based on time of day.

        Args:
            min_activity: Minimum activity level required (0-2.0)
            current_time: Time to check (default: now)

        Returns:
            Tuple of (should_trade, session, activity_level)
        """
        session = self.get_current_session(current_time)
        activity = self.session_activity.get(session, 1.0)

        should_trade = activity >= min_activity

        logger.debug(f"Time filter: {session} session, activity={activity:.1f}, "
                    f"should_trade={should_trade}")

        return should_trade, session, activity

    def get_activity_multiplier(self, current_time: Optional[datetime] = None) -> float:
        """
        Get activity multiplier for current time (used for position sizing).

        Args:
            current_time: Time to check (default: now)

        Returns:
            float: Activity multiplier (0.3 - 1.5)
        """
        session = self.get_current_session(current_time)
        return self.session_activity.get(session, 1.0)


class VolatilityRegimeFilter:
    """
    Filter trades based on current volatility regime.

    Different strategies work better in different volatility regimes:
    - Low volatility: Mean reversion, range-bound strategies
    - Medium volatility: Trend following, momentum strategies (BEST)
    - High volatility: Reduce position size, wider stops
    - Extreme volatility: Avoid trading or use very small positions
    """

    def __init__(self):
        """Initialize volatility regime filter."""
        logger.info("Volatility regime filter initialized")

    def detect_volatility_regime(self, atr_pct: float,
                                 historical_atr: Optional[pd.Series] = None) -> Dict[str, Any]:
        """
        Detect current volatility regime.

        Args:
            atr_pct: Current ATR as percentage of price
            historical_atr: Historical ATR values for comparison

        Returns:
            dict: {
                'regime': str ('low', 'medium', 'high', 'extreme'),
                'percentile': float (if historical data available),
                'trade_multiplier': float (position size adjustment),
                'should_trade': bool
            }
        """
        # Basic ATR-based classification
        if atr_pct < 0.005:
            regime = 'low'
            multiplier = 0.5  # Reduce size in low volatility (choppy)
            should_trade = False  # Avoid choppy markets
        elif atr_pct < 0.015:
            regime = 'medium'
            multiplier = 1.0  # Normal size - ideal conditions
            should_trade = True
        elif atr_pct < 0.03:
            regime = 'high'
            multiplier = 0.7  # Reduce size in high volatility
            should_trade = True
        else:
            regime = 'extreme'
            multiplier = 0.3  # Significantly reduce in extreme volatility
            should_trade = False  # Avoid extreme volatility

        result = {
            'regime': regime,
            'atr_pct': atr_pct,
            'trade_multiplier': multiplier,
            'should_trade': should_trade
        }

        # If historical data available, calculate percentile
        if historical_atr is not None and len(historical_atr) > 20:
            percentile = (historical_atr < atr_pct).sum() / len(historical_atr) * 100
            result['percentile'] = percentile

            # Refine classification based on percentile
            if percentile > 90:
                result['regime'] = 'extreme'
                result['should_trade'] = False
                result['trade_multiplier'] = 0.3
            elif percentile > 70:
                result['regime'] = 'high'
                result['trade_multiplier'] = 0.7

        logger.debug(f"Volatility regime: {result['regime']}, ATR: {atr_pct*100:.2f}%, "
                    f"Multiplier: {result['trade_multiplier']:.1f}")

        return result

    def calculate_optimal_trade_frequency(self, volatility_regime: str) -> Dict[str, Any]:
        """
        Calculate optimal trade frequency based on volatility regime.

        Args:
            volatility_regime: Current volatility regime

        Returns:
            dict: {
                'max_trades_per_day': int,
                'min_time_between_trades_minutes': int,
                'recommended_holding_time_minutes': int
            }
        """
        frequency_map = {
            'low': {
                'max_trades_per_day': 2,
                'min_time_between_trades_minutes': 240,  # 4 hours
                'recommended_holding_time_minutes': 120
            },
            'medium': {
                'max_trades_per_day': 5,
                'min_time_between_trades_minutes': 90,   # 1.5 hours
                'recommended_holding_time_minutes': 60
            },
            'high': {
                'max_trades_per_day': 8,
                'min_time_between_trades_minutes': 45,   # 45 minutes
                'recommended_holding_time_minutes': 30
            },
            'extreme': {
                'max_trades_per_day': 1,  # Very few trades
                'min_time_between_trades_minutes': 360,  # 6 hours
                'recommended_holding_time_minutes': 180
            }
        }

        return frequency_map.get(volatility_regime, frequency_map['medium'])


class NewsEventFilter:
    """
    Filter trades around major news events.

    TODO: Integrate with news APIs and NLP for automated detection
    TODO: Add sentiment analysis for crypto-specific news
    TODO: Track Fed announcements, CPI, unemployment, etc.

    This is a placeholder implementation with manual event configuration.
    Future versions will use ML/NLP to detect and classify news impact.
    """

    def __init__(self):
        """Initialize news event filter."""
        self.scheduled_events: List[Dict] = []
        logger.info("News event filter initialized (manual mode)")
        logger.info("TODO: Integrate news API and NLP for automated event detection")

    def add_event(self, event_time: datetime, event_name: str,
                  impact: str = 'high', buffer_minutes: int = 30) -> None:
        """
        Manually add a scheduled news event.

        Args:
            event_time: When event occurs
            event_name: Description of event
            impact: 'low', 'medium', 'high' (default: high)
            buffer_minutes: Minutes before/after to avoid trading
        """
        event = {
            'time': event_time,
            'name': event_name,
            'impact': impact,
            'buffer_minutes': buffer_minutes
        }
        self.scheduled_events.append(event)
        logger.info(f"Added news event: {event_name} at {event_time}")

    def should_avoid_trading(self, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if we should avoid trading due to nearby news events.

        Args:
            current_time: Time to check (default: now)

        Returns:
            Tuple of (should_avoid, reason)
        """
        if current_time is None:
            current_time = datetime.now()

        for event in self.scheduled_events:
            time_diff = abs((current_time - event['time']).total_seconds() / 60)

            if time_diff <= event['buffer_minutes']:
                reason = f"Near {event['impact']} impact event: {event['name']}"
                logger.warning(f"Trading avoided: {reason}")
                return True, reason

        return False, "No news conflicts"

    def load_economic_calendar(self, calendar_file: str) -> int:
        """
        Load economic calendar from file.

        Args:
            calendar_file: Path to calendar file (JSON or CSV)

        Returns:
            int: Number of events loaded

        TODO: Implement calendar file loading
        TODO: Integrate with economic calendar APIs
        TODO: Auto-update calendar daily
        """
        logger.warning("Economic calendar loading not yet implemented")
        logger.info("TODO: Integrate with news/economic calendar APIs")
        return 0


class SmartFilterAggregator:
    """
    Aggregates all smart filters and provides unified filtering decisions.

    Combines:
    - Time of day filtering
    - Volatility regime filtering
    - News event filtering
    - Additional quality checks

    Returns comprehensive filter results with reasons and adjustments.
    """

    def __init__(self, enable_time_filter: bool = True,
                 enable_volatility_filter: bool = True,
                 enable_news_filter: bool = True):
        """
        Initialize smart filter aggregator.

        Args:
            enable_time_filter: Enable time-of-day filtering
            enable_volatility_filter: Enable volatility regime filtering
            enable_news_filter: Enable news event filtering
        """
        self.time_filter = TimeOfDayFilter() if enable_time_filter else None
        self.volatility_filter = VolatilityRegimeFilter() if enable_volatility_filter else None
        self.news_filter = NewsEventFilter() if enable_news_filter else None

        logger.info(f"Smart Filter Aggregator initialized - "
                   f"Time: {enable_time_filter}, Vol: {enable_volatility_filter}, "
                   f"News: {enable_news_filter}")

    def evaluate_trade_filters(self, atr_pct: float,
                               historical_atr: Optional[pd.Series] = None,
                               current_time: Optional[datetime] = None,
                               min_time_activity: float = 0.5) -> Dict[str, Any]:
        """
        Evaluate all filters and return comprehensive filtering decision.

        Args:
            atr_pct: Current ATR as percentage
            historical_atr: Historical ATR for regime detection
            current_time: Current time (default: now)
            min_time_activity: Minimum time-of-day activity required

        Returns:
            dict: {
                'should_trade': bool,
                'reasons': List[str],
                'adjustments': dict,
                'time_filter': dict,
                'volatility_filter': dict,
                'news_filter': dict
            }
        """
        reasons = []
        adjustments = {
            'position_size_multiplier': 1.0,
            'max_trades_per_day': 5,
            'min_time_between_trades': 90
        }

        overall_should_trade = True

        # Time of day filter
        time_result = {'enabled': False}
        if self.time_filter:
            should_trade_time, session, activity = self.time_filter.should_trade(
                min_time_activity, current_time
            )
            time_result = {
                'enabled': True,
                'should_trade': should_trade_time,
                'session': session,
                'activity': activity
            }

            if not should_trade_time:
                overall_should_trade = False
                reasons.append(f"Low activity period ({session}, activity={activity:.1f})")
            else:
                adjustments['position_size_multiplier'] *= activity
                reasons.append(f"{session.capitalize()} session (activity={activity:.1f})")

        # Volatility regime filter
        volatility_result = {'enabled': False}
        if self.volatility_filter:
            vol_regime = self.volatility_filter.detect_volatility_regime(
                atr_pct, historical_atr
            )
            volatility_result = {
                'enabled': True,
                **vol_regime
            }

            if not vol_regime['should_trade']:
                overall_should_trade = False
                reasons.append(f"{vol_regime['regime'].capitalize()} volatility "
                             f"(ATR={atr_pct*100:.2f}%)")
            else:
                adjustments['position_size_multiplier'] *= vol_regime['trade_multiplier']
                reasons.append(f"{vol_regime['regime'].capitalize()} volatility regime")

            # Get optimal trade frequency
            frequency = self.volatility_filter.calculate_optimal_trade_frequency(
                vol_regime['regime']
            )
            adjustments['max_trades_per_day'] = frequency['max_trades_per_day']
            adjustments['min_time_between_trades'] = frequency['min_time_between_trades_minutes']

        # News filter
        news_result = {'enabled': False}
        if self.news_filter:
            should_avoid, news_reason = self.news_filter.should_avoid_trading(current_time)
            news_result = {
                'enabled': True,
                'should_avoid': should_avoid,
                'reason': news_reason
            }

            if should_avoid:
                overall_should_trade = False
                reasons.append(news_reason)

        # Clamp position size multiplier
        adjustments['position_size_multiplier'] = np.clip(
            adjustments['position_size_multiplier'], 0.3, 1.5
        )

        result = {
            'should_trade': overall_should_trade,
            'reasons': reasons,
            'adjustments': adjustments,
            'time_filter': time_result,
            'volatility_filter': volatility_result,
            'news_filter': news_result
        }

        logger.info(f"Smart filters: should_trade={overall_should_trade}, "
                   f"multiplier={adjustments['position_size_multiplier']:.2f}, "
                   f"reasons={len(reasons)}")

        return result
