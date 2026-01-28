"""
Interest Rate Futures Analyzer
================================

Analyzes interest rate futures to extract market expectations for policy rates.

Features:
- Fed Funds futures probability calculations
- SOFR futures rate expectations
- Treasury futures yield curves
- Rate change probability distributions
- Divergence detection (market vs actual policy)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from .gmig_config import INTEREST_RATE_FUTURES_CONFIG

logger = logging.getLogger("nija.gmig.interest_rates")


class InterestRateFuturesAnalyzer:
    """
    Analyzes interest rate futures to extract market expectations
    
    Key Functions:
    1. Calculate implied rate expectations from futures
    2. Derive probability distributions for rate changes
    3. Detect divergence between market pricing and actual policy
    4. Track rate expectations across time horizons
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Interest Rate Futures Analyzer
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or INTEREST_RATE_FUTURES_CONFIG
        self.tracked_instruments = self.config['tracked_instruments']
        self.probability_threshold = self.config['probability_threshold']
        self.rate_change_threshold = self.config['rate_change_threshold']
        self.forward_periods = self.config['forward_periods']
        
        # Data storage
        self.current_futures_prices: Dict[str, float] = {}
        self.implied_rates: Dict[str, float] = {}
        self.rate_expectations: List[Tuple[datetime, float]] = []
        self.probability_distribution: Dict[float, float] = {}
        
        logger.info(f"InterestRateFuturesAnalyzer initialized tracking {len(self.tracked_instruments)} instruments")
    
    def analyze_rate_expectations(self, current_rate: float = None) -> Dict:
        """
        Analyze market expectations for interest rates
        
        Args:
            current_rate: Current policy rate (Fed Funds)
            
        Returns:
            Dictionary with rate expectations analysis
        """
        logger.info("Analyzing interest rate expectations...")
        
        # In production, would fetch real futures data
        # For now, simulate based on typical market structure
        
        analysis = {
            'timestamp': datetime.now().isoformat(),
            'current_fed_funds_rate': current_rate or 5.50,
            'expectations': {},
            'probabilities': {},
            'signals': [],
        }
        
        # Generate forward rate expectations for next 12 months
        expectations = self._calculate_forward_expectations(current_rate or 5.50)
        analysis['expectations'] = expectations
        
        # Calculate probability of rate changes
        probabilities = self._calculate_rate_change_probabilities(current_rate or 5.50)
        analysis['probabilities'] = probabilities
        
        # Generate trading signals based on expectations
        signals = self._generate_rate_signals(expectations, probabilities)
        analysis['signals'] = signals
        
        return analysis
    
    def _calculate_forward_expectations(self, current_rate: float) -> Dict:
        """
        Calculate forward rate expectations from futures
        
        Args:
            current_rate: Current policy rate
            
        Returns:
            Dictionary mapping time horizons to expected rates
        """
        expectations = {}
        
        # Simulate market expectations
        # In production, would derive from actual futures prices
        
        # Example: Market expects gradual cuts over next year
        for month in range(1, self.forward_periods + 1):
            # Simulate a path (in reality, derived from futures)
            # This example shows expectations of cuts
            expected_cut = 0.25 * (month / 12)  # 25 bps cut over 12 months
            expected_rate = current_rate - expected_cut
            
            date = datetime.now() + timedelta(days=30 * month)
            expectations[f"{month}M"] = {
                'date': date.strftime('%Y-%m-%d'),
                'expected_rate': round(expected_rate, 2),
                'change_from_current': round(-expected_cut, 2),
            }
        
        return expectations
    
    def _calculate_rate_change_probabilities(self, current_rate: float) -> Dict:
        """
        Calculate probability distribution for rate changes
        
        Args:
            current_rate: Current policy rate
            
        Returns:
            Dictionary with probabilities for various rate scenarios
        """
        # In production, would use options on futures to derive probabilities
        # For now, simulate based on typical market structure
        
        probabilities = {
            'next_meeting': {},
            'next_3_months': {},
            'next_6_months': {},
            'next_12_months': {},
        }
        
        # Simulate next meeting probabilities (simplified)
        probabilities['next_meeting'] = {
            'no_change': 0.70,
            'cut_25bps': 0.25,
            'cut_50bps': 0.05,
            'hike_25bps': 0.00,
        }
        
        # 3-month probabilities
        probabilities['next_3_months'] = {
            'cuts_0-25bps': 0.30,
            'cuts_25-50bps': 0.45,
            'cuts_50-75bps': 0.20,
            'cuts_75-100bps': 0.05,
        }
        
        # 6-month probabilities
        probabilities['next_6_months'] = {
            'cuts_0-50bps': 0.20,
            'cuts_50-100bps': 0.50,
            'cuts_100-150bps': 0.25,
            'cuts_150-200bps': 0.05,
        }
        
        # 12-month probabilities
        probabilities['next_12_months'] = {
            'cuts_0-50bps': 0.10,
            'cuts_50-100bps': 0.30,
            'cuts_100-150bps': 0.40,
            'cuts_150-200bps': 0.15,
            'cuts_200bps+': 0.05,
        }
        
        return probabilities
    
    def _generate_rate_signals(self, expectations: Dict, probabilities: Dict) -> List[Dict]:
        """
        Generate trading signals based on rate expectations
        
        Args:
            expectations: Forward rate expectations
            probabilities: Rate change probabilities
            
        Returns:
            List of signal dictionaries
        """
        signals = []
        
        # Signal 1: Near-term rate expectations
        next_3m = expectations.get('3M', {})
        if next_3m:
            change = next_3m.get('change_from_current', 0)
            if abs(change) >= self.rate_change_threshold:
                signal = {
                    'type': 'rate_expectation',
                    'horizon': '3M',
                    'expected_change': change,
                    'direction': 'dovish' if change < 0 else 'hawkish',
                    'magnitude': abs(change),
                    'trading_implication': self._get_trading_implication(change),
                }
                signals.append(signal)
        
        # Signal 2: High probability events
        next_meeting_probs = probabilities.get('next_meeting', {})
        for scenario, prob in next_meeting_probs.items():
            if prob >= self.probability_threshold and scenario != 'no_change':
                signal = {
                    'type': 'probability_event',
                    'horizon': 'next_meeting',
                    'scenario': scenario,
                    'probability': prob,
                    'trading_implication': self._get_probability_implication(scenario, prob),
                }
                signals.append(signal)
        
        # Signal 3: Yield curve positioning
        if len(expectations) >= 6:
            curve_signal = self._analyze_expectations_curve(expectations)
            if curve_signal:
                signals.append(curve_signal)
        
        return signals
    
    def _get_trading_implication(self, rate_change: float) -> str:
        """Get trading implication from rate change"""
        if rate_change < -0.50:
            return "Strong dovish signal - risk assets positive, bonds rally"
        elif rate_change < 0:
            return "Dovish signal - supportive for risk assets"
        elif rate_change > 0.50:
            return "Strong hawkish signal - risk assets negative, bonds sell"
        elif rate_change > 0:
            return "Hawkish signal - headwind for risk assets"
        else:
            return "Neutral - no significant policy change expected"
    
    def _get_probability_implication(self, scenario: str, probability: float) -> str:
        """Get trading implication from probability scenario"""
        if 'cut' in scenario.lower():
            return f"High probability ({probability:.0%}) of rate cut - positive for risk assets"
        elif 'hike' in scenario.lower():
            return f"High probability ({probability:.0%}) of rate hike - negative for risk assets"
        else:
            return f"Scenario {scenario} with {probability:.0%} probability"
    
    def _analyze_expectations_curve(self, expectations: Dict) -> Optional[Dict]:
        """
        Analyze the shape of rate expectations curve
        
        Args:
            expectations: Forward rate expectations
            
        Returns:
            Signal dictionary or None
        """
        # Extract rates at different points
        rates = [exp.get('expected_rate', 0) for exp in expectations.values()]
        
        if len(rates) < 3:
            return None
        
        # Calculate curve slope
        start_rate = rates[0]
        mid_rate = rates[len(rates) // 2]
        end_rate = rates[-1]
        
        total_change = end_rate - start_rate
        
        # Determine curve shape
        if total_change < -0.50:
            shape = "steep_cutting_cycle"
            implication = "Market pricing aggressive easing - very bullish for risk assets"
        elif total_change < 0:
            shape = "gradual_cutting_cycle"
            implication = "Market pricing gradual easing - bullish for risk assets"
        elif total_change > 0.50:
            shape = "steep_hiking_cycle"
            implication = "Market pricing aggressive tightening - very bearish for risk assets"
        elif total_change > 0:
            shape = "gradual_hiking_cycle"
            implication = "Market pricing gradual tightening - bearish for risk assets"
        else:
            shape = "flat"
            implication = "Market pricing stable rates - neutral"
        
        return {
            'type': 'expectations_curve',
            'shape': shape,
            'total_change_12m': round(total_change, 2),
            'implication': implication,
        }
    
    def calculate_fed_funds_probabilities(self, futures_prices: List[float],
                                         current_rate: float) -> Dict[str, float]:
        """
        Calculate Fed Funds rate change probabilities from futures
        
        This is the classic CME FedWatch tool calculation
        
        Args:
            futures_prices: List of Fed Funds futures prices
            current_rate: Current Fed Funds rate
            
        Returns:
            Dictionary mapping scenarios to probabilities
        """
        # Fed Funds futures price = 100 - implied rate
        # Simplified calculation for demonstration
        
        if not futures_prices:
            return {}
        
        # Calculate implied rate from nearest contract
        implied_rate = 100 - futures_prices[0]
        
        # Calculate probability of rate change
        rate_diff = implied_rate - current_rate
        
        # Discretize into 25 bps increments
        bps_change = round(rate_diff / 0.25) * 0.25
        
        # Generate probability distribution
        # (In reality, would use multiple contracts and options)
        
        probabilities = {}
        if abs(bps_change) < 0.125:
            probabilities['no_change'] = 0.80
            probabilities['cut_25bps'] = 0.15
            probabilities['hike_25bps'] = 0.05
        elif bps_change <= -0.25:
            # Expecting cuts
            probabilities['no_change'] = 0.20
            probabilities['cut_25bps'] = 0.60
            probabilities['cut_50bps'] = 0.20
        elif bps_change >= 0.25:
            # Expecting hikes
            probabilities['no_change'] = 0.20
            probabilities['hike_25bps'] = 0.60
            probabilities['hike_50bps'] = 0.20
        
        return probabilities
    
    def get_summary(self) -> Dict:
        """
        Get summary of interest rate analysis
        
        Returns:
            Summary dictionary
        """
        analysis = self.analyze_rate_expectations()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'tracked_instruments': self.tracked_instruments,
            'current_analysis': analysis,
            'signals_count': len(analysis.get('signals', [])),
            'forward_periods': self.forward_periods,
        }
