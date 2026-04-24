"""
Central Bank Monitor
====================

Monitors global central bank activities, policy decisions, and forward guidance.

Features:
- Track policy rate changes
- Monitor meeting schedules
- Analyze forward guidance
- Detect emergency actions
- Quantitative easing/tightening tracking
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging
import os
import requests

from .gmig_config import CENTRAL_BANK_CONFIG

logger = logging.getLogger("nija.gmig.central_bank")


class CentralBank(Enum):
    """Major central banks tracked by the system"""
    FED = "fed"          # US Federal Reserve
    ECB = "ecb"          # European Central Bank
    BOJ = "boj"          # Bank of Japan
    BOE = "boe"          # Bank of England
    PBOC = "pboc"        # People's Bank of China
    SNB = "snb"          # Swiss National Bank
    BOC = "boc"          # Bank of Canada
    RBA = "rba"          # Reserve Bank of Australia


class PolicyAction(Enum):
    """Types of policy actions"""
    RATE_HIKE = "rate_hike"
    RATE_CUT = "rate_cut"
    QE_START = "qe_start"           # Quantitative Easing
    QE_INCREASE = "qe_increase"
    QT_START = "qt_start"           # Quantitative Tightening
    QT_INCREASE = "qt_increase"
    EMERGENCY_ACTION = "emergency"
    FORWARD_GUIDANCE = "guidance"
    NO_CHANGE = "no_change"


class CentralBankMonitor:
    """
    Monitors global central bank policy decisions and forward guidance

    Key Functions:
    1. Track policy rate changes
    2. Monitor meeting schedules
    3. Analyze forward guidance and statements
    4. Detect emergency or unconventional actions
    5. Score policy stance (dovish/hawkish)
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Central Bank Monitor

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or CENTRAL_BANK_CONFIG
        self.tracked_banks = [CentralBank(bank.lower()) for bank in self.config['tracked_banks']]
        self.policy_impact_weights = self.config['policy_impact_weight']

        # Historical data storage
        self.policy_history: Dict[CentralBank, List[Dict]] = {bank: [] for bank in self.tracked_banks}
        self.current_rates: Dict[CentralBank, float] = {}
        self.next_meetings: Dict[CentralBank, Optional[datetime]] = {}
        self.policy_stance: Dict[CentralBank, float] = {}  # -1 (dovish) to +1 (hawkish)

        # FRED API for US data
        self.fred_api_key = os.getenv('FRED_API_KEY')
        self.use_fred = self.fred_api_key is not None

        logger.info(f"CentralBankMonitor initialized tracking {len(self.tracked_banks)} central banks")

    def update_all_banks(self) -> Dict:
        """
        Update data for all tracked central banks

        Returns:
            Dictionary with updates for all banks
        """
        logger.info("Updating all central bank data...")

        updates = {}
        for bank in self.tracked_banks:
            try:
                update = self._update_bank(bank)
                updates[bank.value] = update
            except Exception as e:
                logger.error(f"Error updating {bank.value}: {e}")
                updates[bank.value] = {'error': str(e)}

        # Calculate aggregate policy stance
        aggregate_stance = self._calculate_aggregate_stance()
        updates['aggregate_stance'] = aggregate_stance

        return updates

    def _update_bank(self, bank: CentralBank) -> Dict:
        """
        Update data for a specific central bank

        Args:
            bank: Central bank to update

        Returns:
            Dictionary with bank-specific updates
        """
        if bank == CentralBank.FED:
            return self._update_fed()
        elif bank == CentralBank.ECB:
            return self._update_ecb()
        elif bank == CentralBank.BOJ:
            return self._update_boj()
        elif bank == CentralBank.BOE:
            return self._update_boe()
        elif bank == CentralBank.PBOC:
            return self._update_pboc()
        else:
            # For other banks, use generic update
            return self._update_generic(bank)

    def _update_fed(self) -> Dict:
        """Update Federal Reserve data"""
        update = {
            'bank': 'FED',
            'timestamp': datetime.now().isoformat(),
        }

        # Try to fetch from FRED if available
        if self.use_fred:
            try:
                # Federal Funds Effective Rate (DFF)
                rate_data = self._fetch_fred_series('DFF', days=90)
                if rate_data is not None and len(rate_data) > 0:
                    current_rate = float(rate_data.iloc[-1])
                    self.current_rates[CentralBank.FED] = current_rate
                    update['current_rate'] = current_rate
                    update['rate_source'] = 'FRED'

                    # Calculate recent change
                    if len(rate_data) >= 30:
                        rate_30d_ago = float(rate_data.iloc[-30])
                        rate_change_30d = current_rate - rate_30d_ago
                        update['rate_change_30d'] = rate_change_30d

                # Also fetch 10-year treasury for context
                treasury_10y = self._fetch_fred_series('DGS10', days=90)
                if treasury_10y is not None and len(treasury_10y) > 0:
                    update['treasury_10y'] = float(treasury_10y.iloc[-1])

            except Exception as e:
                logger.warning(f"Error fetching FRED data for FED: {e}")
                update['error'] = str(e)

        # Calculate policy stance
        stance = self._calculate_policy_stance(CentralBank.FED)
        self.policy_stance[CentralBank.FED] = stance
        update['policy_stance'] = stance
        update['stance_description'] = self._describe_stance(stance)

        # Add next meeting date (FOMC meets 8 times per year)
        update['next_meeting'] = self._estimate_next_meeting(CentralBank.FED)

        return update

    def _update_ecb(self) -> Dict:
        """Update European Central Bank data"""
        update = {
            'bank': 'ECB',
            'timestamp': datetime.now().isoformat(),
        }

        # ECB policy rates (would integrate with ECB API in production)
        # For now, use simulated/cached data
        update['current_rate'] = self.current_rates.get(CentralBank.ECB, 4.50)
        update['data_source'] = 'cached'

        stance = self._calculate_policy_stance(CentralBank.ECB)
        self.policy_stance[CentralBank.ECB] = stance
        update['policy_stance'] = stance
        update['stance_description'] = self._describe_stance(stance)

        return update

    def _update_boj(self) -> Dict:
        """Update Bank of Japan data"""
        update = {
            'bank': 'BOJ',
            'timestamp': datetime.now().isoformat(),
        }

        # BOJ is unique - negative interest rate policy
        update['current_rate'] = self.current_rates.get(CentralBank.BOJ, -0.10)
        update['data_source'] = 'cached'
        update['special_policy'] = 'Yield Curve Control'

        stance = self._calculate_policy_stance(CentralBank.BOJ)
        self.policy_stance[CentralBank.BOJ] = stance
        update['policy_stance'] = stance
        update['stance_description'] = self._describe_stance(stance)

        return update

    def _update_boe(self) -> Dict:
        """Update Bank of England data"""
        update = {
            'bank': 'BOE',
            'timestamp': datetime.now().isoformat(),
        }

        update['current_rate'] = self.current_rates.get(CentralBank.BOE, 5.25)
        update['data_source'] = 'cached'

        stance = self._calculate_policy_stance(CentralBank.BOE)
        self.policy_stance[CentralBank.BOE] = stance
        update['policy_stance'] = stance
        update['stance_description'] = self._describe_stance(stance)

        return update

    def _update_pboc(self) -> Dict:
        """Update People's Bank of China data"""
        update = {
            'bank': 'PBOC',
            'timestamp': datetime.now().isoformat(),
        }

        # PBOC uses Loan Prime Rate (LPR)
        update['lpr_1y'] = self.current_rates.get(CentralBank.PBOC, 3.45)
        update['data_source'] = 'cached'

        stance = self._calculate_policy_stance(CentralBank.PBOC)
        self.policy_stance[CentralBank.PBOC] = stance
        update['policy_stance'] = stance
        update['stance_description'] = self._describe_stance(stance)

        return update

    def _update_generic(self, bank: CentralBank) -> Dict:
        """Generic update for other central banks"""
        return {
            'bank': bank.value.upper(),
            'timestamp': datetime.now().isoformat(),
            'current_rate': self.current_rates.get(bank, 0.0),
            'data_source': 'cached',
        }

    def _fetch_fred_series(self, series_id: str, days: int = 90) -> Optional[pd.Series]:
        """
        Fetch economic data from FRED API

        Args:
            series_id: FRED series identifier
            days: Number of days to fetch

        Returns:
            pandas Series with data or None if error
        """
        if not self.use_fred:
            return None

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            url = f"https://api.stlouisfed.org/fred/series/observations"
            params = {
                'series_id': series_id,
                'api_key': self.fred_api_key,
                'file_type': 'json',
                'observation_start': start_date.strftime('%Y-%m-%d'),
                'observation_end': end_date.strftime('%Y-%m-%d'),
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            observations = data.get('observations', [])

            if not observations:
                return None

            # Convert to pandas Series
            df = pd.DataFrame(observations)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df['value'] = pd.to_numeric(df['value'], errors='coerce')

            return df['value'].dropna()

        except Exception as e:
            logger.warning(f"Error fetching FRED series {series_id}: {e}")
            return None

    def _calculate_policy_stance(self, bank: CentralBank) -> float:
        """
        Calculate policy stance from -1 (very dovish) to +1 (very hawkish)

        Args:
            bank: Central bank to analyze

        Returns:
            Stance score from -1 to +1
        """
        # This would analyze:
        # 1. Recent rate changes
        # 2. Forward guidance language
        # 3. Balance sheet changes
        # 4. Communication tone

        # Simplified version based on rate level
        rate = self.current_rates.get(bank, 0)

        # Normalize based on historical context
        if bank == CentralBank.FED:
            # Historical range roughly 0-6%
            normalized = (rate - 3.0) / 3.0
        elif bank == CentralBank.ECB:
            normalized = (rate - 2.0) / 2.0
        elif bank == CentralBank.BOJ:
            # BOJ is special (negative rates)
            normalized = -0.8  # Generally dovish
        else:
            normalized = (rate - 2.5) / 2.5

        # Clip to [-1, 1]
        return max(-1.0, min(1.0, normalized))

    def _describe_stance(self, stance: float) -> str:
        """Convert stance score to description"""
        if stance < -0.6:
            return "Very Dovish"
        elif stance < -0.2:
            return "Dovish"
        elif stance < 0.2:
            return "Neutral"
        elif stance < 0.6:
            return "Hawkish"
        else:
            return "Very Hawkish"

    def _calculate_aggregate_stance(self) -> Dict:
        """
        Calculate weighted aggregate policy stance across all banks

        Returns:
            Dictionary with aggregate stance metrics
        """
        weighted_sum = 0.0
        total_weight = 0.0

        for bank in self.tracked_banks:
            stance = self.policy_stance.get(bank, 0.0)
            weight = self.policy_impact_weights.get(bank.value.upper(), 0.5)

            weighted_sum += stance * weight
            total_weight += weight

        aggregate = weighted_sum / total_weight if total_weight > 0 else 0.0

        return {
            'aggregate_stance': aggregate,
            'description': self._describe_stance(aggregate),
            'dovish_count': sum(1 for s in self.policy_stance.values() if s < -0.2),
            'hawkish_count': sum(1 for s in self.policy_stance.values() if s > 0.2),
            'neutral_count': sum(1 for s in self.policy_stance.values() if -0.2 <= s <= 0.2),
        }

    def _estimate_next_meeting(self, bank: CentralBank) -> str:
        """
        Estimate next policy meeting date

        Args:
            bank: Central bank

        Returns:
            ISO formatted date string
        """
        # In production, would use actual calendar
        # For now, estimate based on typical schedules
        now = datetime.now()

        if bank == CentralBank.FED:
            # FOMC meets roughly every 6 weeks
            next_meeting = now + timedelta(days=42)
        elif bank == CentralBank.ECB:
            # ECB meets every 6 weeks
            next_meeting = now + timedelta(days=42)
        elif bank == CentralBank.BOJ:
            # BOJ meets every 6-8 weeks
            next_meeting = now + timedelta(days=49)
        else:
            # Default to monthly
            next_meeting = now + timedelta(days=30)

        return next_meeting.strftime('%Y-%m-%d')

    def detect_emergency_action(self) -> Optional[Dict]:
        """
        Detect if any central bank has taken emergency action

        Returns:
            Dictionary with emergency action details or None
        """
        # Would check for:
        # - Unscheduled meetings
        # - Emergency rate cuts
        # - New QE programs
        # - Swap line activations
        # - Crisis facilities

        # Placeholder for now
        return None

    def get_summary(self) -> Dict:
        """
        Get summary of central bank monitoring

        Returns:
            Summary dictionary
        """
        aggregate = self._calculate_aggregate_stance()

        return {
            'timestamp': datetime.now().isoformat(),
            'tracked_banks': [bank.value.upper() for bank in self.tracked_banks],
            'aggregate_stance': aggregate,
            'current_rates': {bank.value.upper(): rate for bank, rate in self.current_rates.items()},
            'policy_stances': {bank.value.upper(): self._describe_stance(stance)
                             for bank, stance in self.policy_stance.items()},
            'use_fred_api': self.use_fred,
        }
