"""
Crisis Early-Warning System
=============================

Multi-indicator crisis detection system with pattern matching against historical crises.

Features:
- Real-time crisis probability scoring
- Historical crisis pattern matching
- Multi-level alert system
- Automated defensive positioning triggers
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
import logging

from .gmig_config import CRISIS_WARNING_CONFIG

logger = logging.getLogger("nija.gmig.crisis")


class AlertLevel(Enum):
    """Crisis alert levels"""
    GREEN = "green"      # Normal - no crisis signals
    YELLOW = "yellow"    # Caution - elevated risk
    ORANGE = "orange"    # Warning - high crisis probability
    RED = "red"          # Emergency - crisis imminent/active


class CrisisWarningSystem:
    """
    Early-warning system for financial market crises
    
    Methodology:
    1. Monitor multiple crisis indicators
    2. Compare to historical crisis patterns
    3. Calculate crisis probability
    4. Issue graduated alerts
    5. Trigger defensive positioning
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Crisis Warning System
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or CRISIS_WARNING_CONFIG
        self.alert_levels_config = self.config['alert_levels']
        self.indicators = self.config['indicators']
        self.crisis_patterns = self.config['crisis_patterns']
        self.confidence_threshold = self.config['confidence_threshold']
        
        # Current state
        self.current_alert_level: AlertLevel = AlertLevel.GREEN
        self.crisis_probability: float = 0.0
        self.indicator_readings: Dict[str, float] = {}
        self.pattern_matches: Dict[str, float] = {}
        
        logger.info("CrisisWarningSystem initialized")
    
    def assess_crisis_risk(self, 
                          yield_curve_data: Dict = None,
                          liquidity_data: Dict = None,
                          central_bank_data: Dict = None) -> Dict:
        """
        Assess current crisis risk across all indicators
        
        Args:
            yield_curve_data: Data from YieldCurveAIModeler
            liquidity_data: Data from LiquidityStressDetector
            central_bank_data: Data from CentralBankMonitor
            
        Returns:
            Comprehensive crisis risk assessment
        """
        logger.info("Assessing crisis risk...")
        
        # Collect indicator readings
        self.indicator_readings = self._collect_indicator_readings(
            yield_curve_data, liquidity_data, central_bank_data
        )
        
        # Match against historical crisis patterns
        self.pattern_matches = self._match_crisis_patterns()
        
        # Calculate overall crisis probability
        self.crisis_probability = self._calculate_crisis_probability()
        
        # Determine alert level
        self.current_alert_level = self._determine_alert_level()
        
        assessment = {
            'timestamp': datetime.now().isoformat(),
            'alert_level': self.current_alert_level.value,
            'crisis_probability': self.crisis_probability,
            'indicator_readings': self.indicator_readings,
            'pattern_matches': self.pattern_matches,
            'warnings': [],
            'recommended_actions': [],
        }
        
        # Generate warnings
        warnings = self._generate_warnings()
        assessment['warnings'] = warnings
        
        # Get recommended actions
        actions = self._get_recommended_actions()
        assessment['recommended_actions'] = actions
        
        # Add historical context
        assessment['similar_periods'] = self._find_similar_periods()
        
        return assessment
    
    def _collect_indicator_readings(self,
                                   yield_curve_data: Dict = None,
                                   liquidity_data: Dict = None,
                                   central_bank_data: Dict = None) -> Dict[str, float]:
        """
        Collect current readings for all crisis indicators
        
        Args:
            yield_curve_data: Yield curve analysis
            liquidity_data: Liquidity stress analysis
            central_bank_data: Central bank monitoring data
            
        Returns:
            Dictionary mapping indicators to severity scores (0-1)
        """
        readings = {}
        
        # Yield curve indicators
        if yield_curve_data:
            inversion = yield_curve_data.get('spreads', {}).get('2y_10y', 0)
            readings['yield_curve_inversion'] = 1.0 if inversion < -0.25 else max(0, -inversion / 0.25)
        else:
            readings['yield_curve_inversion'] = 0.0
        
        # Liquidity stress indicators
        if liquidity_data:
            stress_score = liquidity_data.get('overall_stress_score', 0)
            readings['liquidity_stress'] = stress_score
            
            # Specific liquidity metrics
            metrics = liquidity_data.get('metrics', {})
            ted_spread = metrics.get('ted_spread', 0)
            readings['ted_spread_level'] = min(1.0, ted_spread / 2.0)  # Normalize to crisis level
            
            vix = metrics.get('vix', 20)
            readings['equity_volatility_spike'] = min(1.0, max(0, (vix - 20) / 40))
        else:
            readings['liquidity_stress'] = 0.0
            readings['ted_spread_level'] = 0.0
            readings['equity_volatility_spike'] = 0.0
        
        # Central bank indicators
        if central_bank_data:
            aggregate_stance = central_bank_data.get('aggregate_stance', {})
            stance_value = aggregate_stance.get('aggregate_stance', 0)
            # Emergency action if very dovish turn
            readings['central_bank_emergency_action'] = max(0, -stance_value) if stance_value < -0.5 else 0.0
        else:
            readings['central_bank_emergency_action'] = 0.0
        
        # Additional indicators (simulated for now)
        readings['credit_spread_blowout'] = 0.15  # Would fetch actual HY spreads
        readings['cross_asset_correlation_breakdown'] = 0.10
        readings['repo_market_stress'] = 0.05
        readings['currency_volatility'] = 0.08
        
        return readings
    
    def _match_crisis_patterns(self) -> Dict[str, float]:
        """
        Match current conditions to historical crisis patterns
        
        Returns:
            Dictionary mapping crisis names to similarity scores (0-1)
        """
        matches = {}
        
        for crisis_name, crisis_pattern in self.crisis_patterns.items():
            # Calculate similarity to this crisis pattern
            similarity = self._calculate_pattern_similarity(crisis_pattern)
            matches[crisis_name] = similarity
        
        return matches
    
    def _calculate_pattern_similarity(self, pattern: Dict) -> float:
        """
        Calculate similarity between current conditions and a crisis pattern
        
        Args:
            pattern: Dictionary with crisis pattern indicators
            
        Returns:
            Similarity score (0-1)
        """
        # Compare key indicators
        similarities = []
        
        # TED spread comparison
        current_ted = self.indicator_readings.get('ted_spread_level', 0) * 2.0  # Denormalize
        pattern_ted = pattern.get('ted_spread', 0)
        if pattern_ted > 0:
            ted_sim = 1.0 - min(1.0, abs(current_ted - pattern_ted) / pattern_ted)
            similarities.append(ted_sim)
        
        # VIX comparison
        current_vix_norm = self.indicator_readings.get('equity_volatility_spike', 0)
        current_vix = 20 + current_vix_norm * 40
        pattern_vix = pattern.get('vix', 20)
        if pattern_vix > 0:
            vix_sim = 1.0 - min(1.0, abs(current_vix - pattern_vix) / pattern_vix)
            similarities.append(vix_sim)
        
        # Yield curve comparison
        current_yc = self.indicator_readings.get('yield_curve_inversion', 0)
        pattern_yc = abs(pattern.get('yield_curve', 0))
        yc_sim = 1.0 - abs(current_yc - pattern_yc)
        similarities.append(max(0, yc_sim))
        
        # Credit spread comparison
        pattern_credit = pattern.get('credit_spread', 0)
        # Simplified - would use actual credit spreads
        similarities.append(0.5)
        
        # Average similarity
        return np.mean(similarities) if similarities else 0.0
    
    def _calculate_crisis_probability(self) -> float:
        """
        Calculate overall crisis probability from all indicators
        
        Returns:
            Crisis probability (0-1)
        """
        # Weight different indicators
        weights = {
            'yield_curve_inversion': 0.20,
            'liquidity_stress': 0.25,
            'central_bank_emergency_action': 0.15,
            'credit_spread_blowout': 0.15,
            'equity_volatility_spike': 0.10,
            'cross_asset_correlation_breakdown': 0.05,
            'repo_market_stress': 0.05,
            'ted_spread_level': 0.05,
        }
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for indicator, reading in self.indicator_readings.items():
            weight = weights.get(indicator, 0.0)
            weighted_sum += reading * weight
            total_weight += weight
        
        base_probability = weighted_sum / total_weight if total_weight > 0 else 0.0
        
        # Boost probability if matching historical crisis patterns
        max_pattern_match = max(self.pattern_matches.values()) if self.pattern_matches else 0.0
        pattern_boost = max_pattern_match * 0.20  # Up to 20% boost
        
        final_probability = min(1.0, base_probability + pattern_boost)
        
        return round(final_probability, 3)
    
    def _determine_alert_level(self) -> AlertLevel:
        """
        Determine alert level from crisis probability
        
        Returns:
            AlertLevel enum
        """
        for level_name in ['red', 'orange', 'yellow', 'green']:
            level_config = self.alert_levels_config[level_name]
            threshold = level_config['threshold']
            
            if self.crisis_probability >= threshold:
                return AlertLevel(level_name)
        
        return AlertLevel.GREEN
    
    def _generate_warnings(self) -> List[Dict]:
        """
        Generate specific warnings based on indicator levels
        
        Returns:
            List of warning dictionaries
        """
        warnings = []
        
        # Check each indicator for warning levels
        for indicator, reading in self.indicator_readings.items():
            if reading >= 0.50:  # Warning threshold
                warning = {
                    'indicator': indicator,
                    'severity': self._get_severity_from_reading(reading),
                    'reading': reading,
                    'message': self._get_indicator_message(indicator, reading),
                }
                warnings.append(warning)
        
        # Pattern match warnings
        for crisis_name, similarity in self.pattern_matches.items():
            if similarity >= 0.60:  # High similarity
                warnings.append({
                    'indicator': 'historical_pattern',
                    'severity': 'high',
                    'reading': similarity,
                    'message': f"Current conditions {similarity:.0%} similar to {crisis_name.replace('_', ' ').title()}",
                })
        
        return warnings
    
    def _get_severity_from_reading(self, reading: float) -> str:
        """Get severity level from reading"""
        if reading >= 0.80:
            return 'critical'
        elif reading >= 0.60:
            return 'high'
        elif reading >= 0.40:
            return 'medium'
        else:
            return 'low'
    
    def _get_indicator_message(self, indicator: str, reading: float) -> str:
        """Get warning message for indicator"""
        messages = {
            'yield_curve_inversion': "Yield curve inversion signals recession risk",
            'liquidity_stress': "Market liquidity showing stress",
            'central_bank_emergency_action': "Central bank emergency measures detected",
            'credit_spread_blowout': "Credit spreads widening significantly",
            'equity_volatility_spike': "Equity volatility at elevated levels",
            'cross_asset_correlation_breakdown': "Correlation breakdown indicates risk-off",
            'repo_market_stress': "Repo market showing funding stress",
            'currency_volatility': "Currency markets showing stress",
        }
        
        base_msg = messages.get(indicator, f"{indicator} elevated")
        return f"{base_msg} (level: {reading:.1%})"
    
    def _get_recommended_actions(self) -> List[str]:
        """
        Get recommended actions based on alert level
        
        Returns:
            List of action strings
        """
        level_config = self.alert_levels_config[self.current_alert_level.value]
        action_type = level_config.get('action', 'standard_operation')
        
        actions = []
        
        if action_type == 'emergency_defensive':
            actions = [
                "🚨 EMERGENCY: Move to maximum defensive positioning",
                "Liquidate all speculative positions immediately",
                "Convert 80%+ of portfolio to cash/safe havens",
                "Hold only highest quality assets (Treasury bonds, USD, gold)",
                "Activate all hedging strategies",
                "Suspend new position entries",
                "Monitor continuously for central bank interventions",
            ]
        elif action_type == 'reduce_positions':
            actions = [
                "⚠️ HIGH RISK: Implement significant risk reduction",
                "Reduce overall exposure by 50-70%",
                "Close all leveraged positions",
                "Exit low-quality and high-beta positions",
                "Tighten all stop losses",
                "Increase cash reserves to 40%+",
                "Add defensive hedges if not already in place",
            ]
        elif action_type == 'increase_monitoring':
            actions = [
                "⚡ ELEVATED RISK: Increase monitoring frequency",
                "Review and update risk limits",
                "Reduce position sizes by 20-30%",
                "Be prepared for rapid defensive action",
                "Avoid new high-risk positions",
                "Review correlation assumptions",
                "Check hedge effectiveness",
            ]
        else:  # standard_operation
            actions = [
                "✅ NORMAL: Continue standard operations",
                "Maintain normal risk management practices",
                "Keep monitoring crisis indicators",
            ]
        
        return actions
    
    def _find_similar_periods(self) -> List[Dict]:
        """
        Find historical periods with similar conditions
        
        Returns:
            List of similar period dictionaries
        """
        # Return crisis patterns sorted by similarity
        sorted_patterns = sorted(
            self.pattern_matches.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        similar = []
        for crisis_name, similarity in sorted_patterns[:3]:
            if similarity > 0.30:  # Only include if somewhat similar
                similar.append({
                    'period': crisis_name.replace('_', ' ').title(),
                    'similarity': similarity,
                    'confidence': 'high' if similarity > 0.60 else 'medium' if similarity > 0.45 else 'low',
                })
        
        return similar
    
    def get_summary(self) -> Dict:
        """
        Get summary of crisis warning assessment
        
        Returns:
            Summary dictionary
        """
        return {
            'timestamp': datetime.now().isoformat(),
            'alert_level': self.current_alert_level.value,
            'alert_description': self.alert_levels_config[self.current_alert_level.value]['description'],
            'crisis_probability': self.crisis_probability,
            'active_warnings': len([w for w in self._generate_warnings() if w.get('severity') in ['high', 'critical']]),
            'top_concerns': self._get_top_concerns(),
        }
    
    def _get_top_concerns(self) -> List[str]:
        """Get top 3 crisis concerns"""
        # Sort indicators by reading
        sorted_indicators = sorted(
            self.indicator_readings.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        concerns = []
        for indicator, reading in sorted_indicators[:3]:
            if reading > 0.30:  # Only include if elevated
                concerns.append(f"{indicator.replace('_', ' ')}: {reading:.0%}")
        
        return concerns
