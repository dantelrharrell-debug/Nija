"""
Liquidity Stress Detector
==========================

Detects liquidity stress in financial markets through multiple indicators.

Features:
- TED spread monitoring
- LIBOR-OIS spread tracking
- VIX and volatility indices
- High-yield credit spreads
- Repo market monitoring
- Cross-market liquidity analysis
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
import logging

from .gmig_config import LIQUIDITY_STRESS_CONFIG

logger = logging.getLogger("nija.gmig.liquidity")


class StressLevel(Enum):
    """Liquidity stress levels"""
    GREEN = "green"      # Normal conditions
    YELLOW = "yellow"    # Elevated stress
    ORANGE = "orange"    # High stress
    RED = "red"          # Crisis conditions


class LiquidityStressDetector:
    """
    Detects liquidity stress in financial markets

    Key Indicators:
    1. TED Spread (3M LIBOR - 3M T-Bill)
    2. LIBOR-OIS Spread
    3. VIX (equity volatility)
    4. MOVE Index (bond volatility)
    5. High-yield credit spreads
    6. Repo market rates
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Liquidity Stress Detector

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or LIQUIDITY_STRESS_CONFIG
        self.metrics_config = self.config['metrics']
        self.stress_thresholds = self.config['stress_score_threshold']

        # Current readings
        self.current_metrics: Dict[str, float] = {}
        self.stress_scores: Dict[str, float] = {}
        self.overall_stress_level: StressLevel = StressLevel.GREEN
        self.overall_stress_score: float = 0.0

        logger.info("LiquidityStressDetector initialized")

    def detect_stress(self) -> Dict:
        """
        Detect liquidity stress across all monitored indicators

        Returns:
            Comprehensive stress analysis
        """
        logger.info("Detecting liquidity stress...")

        # Fetch current metrics
        self.current_metrics = self._fetch_current_metrics()

        # Calculate stress scores for each metric
        self.stress_scores = self._calculate_stress_scores()

        # Calculate overall stress level
        self.overall_stress_score = self._calculate_overall_stress()
        self.overall_stress_level = self._determine_stress_level(self.overall_stress_score)

        analysis = {
            'timestamp': datetime.now().isoformat(),
            'overall_stress_level': self.overall_stress_level.value,
            'overall_stress_score': self.overall_stress_score,
            'metrics': self.current_metrics,
            'stress_scores': self.stress_scores,
            'alerts': [],
            'recommendations': [],
        }

        # Generate alerts for elevated stress
        alerts = self._generate_stress_alerts()
        analysis['alerts'] = alerts

        # Generate trading recommendations
        recommendations = self._generate_recommendations()
        analysis['recommendations'] = recommendations

        return analysis

    def _fetch_current_metrics(self) -> Dict[str, float]:
        """
        Fetch current liquidity metrics

        In production, would fetch from:
        - FRED API
        - Bloomberg
        - Market data providers

        Returns:
            Dictionary of current metric values
        """
        # Simulated current metrics
        # In production, fetch real data

        metrics = {
            'ted_spread': 0.35,        # Basis points (normal < 50)
            'libor_ois_spread': 0.12,  # Basis points (normal < 10)
            'vix': 18.5,               # VIX index (normal < 20)
            'move_index': 95.0,        # MOVE index (normal < 100)
            'high_yield_spread': 4.50, # Percentage (normal < 4%)
            'repo_overnight': 5.30,    # Percentage
            'repo_term': 5.35,         # Percentage
        }

        return metrics

    def _calculate_stress_scores(self) -> Dict[str, float]:
        """
        Calculate normalized stress scores for each metric

        Returns:
            Dictionary mapping metrics to stress scores (0-1)
        """
        scores = {}

        for metric, value in self.current_metrics.items():
            if metric in self.metrics_config:
                thresholds = self.metrics_config[metric]
                score = self._normalize_metric_to_score(value, thresholds)
                scores[metric] = score

        return scores

    def _normalize_metric_to_score(self, value: float, thresholds: Dict) -> float:
        """
        Normalize metric value to stress score (0-1)

        Args:
            value: Current metric value
            thresholds: Dictionary with normal/elevated/crisis thresholds

        Returns:
            Stress score from 0 (normal) to 1 (crisis)
        """
        normal = thresholds.get('normal', 0)
        elevated = thresholds.get('elevated', 1)
        crisis = thresholds.get('crisis', 2)

        if value <= normal:
            # Normal conditions
            return 0.0
        elif value <= elevated:
            # Elevated stress - linear interpolation
            return 0.5 * (value - normal) / (elevated - normal)
        elif value <= crisis:
            # High stress - linear interpolation
            return 0.5 + 0.3 * (value - elevated) / (crisis - elevated)
        else:
            # Crisis conditions
            excess = (value - crisis) / crisis
            return min(1.0, 0.8 + 0.2 * excess)

    def _calculate_overall_stress(self) -> float:
        """
        Calculate overall stress score from individual metrics

        Returns:
            Overall stress score (0-1)
        """
        if not self.stress_scores:
            return 0.0

        # Weight different metrics
        weights = {
            'ted_spread': 0.25,
            'libor_ois_spread': 0.20,
            'vix': 0.20,
            'move_index': 0.15,
            'high_yield_spread': 0.20,
        }

        weighted_sum = 0.0
        total_weight = 0.0

        for metric, score in self.stress_scores.items():
            weight = weights.get(metric, 0.10)
            weighted_sum += score * weight
            total_weight += weight

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        return round(overall, 3)

    def _determine_stress_level(self, stress_score: float) -> StressLevel:
        """
        Determine stress level from score

        Args:
            stress_score: Overall stress score

        Returns:
            StressLevel enum
        """
        thresholds = self.stress_thresholds

        if stress_score >= thresholds['red']:
            return StressLevel.RED
        elif stress_score >= thresholds['orange']:
            return StressLevel.ORANGE
        elif stress_score >= thresholds['yellow']:
            return StressLevel.YELLOW
        else:
            return StressLevel.GREEN

    def _generate_stress_alerts(self) -> List[Dict]:
        """
        Generate alerts for elevated stress levels

        Returns:
            List of alert dictionaries
        """
        alerts = []

        # Check each metric for concerning levels
        for metric, score in self.stress_scores.items():
            if score >= 0.50:  # Elevated or higher
                alert = {
                    'metric': metric,
                    'current_value': self.current_metrics.get(metric, 0),
                    'stress_score': score,
                    'severity': self._get_alert_severity(score),
                    'message': self._get_alert_message(metric, score),
                }
                alerts.append(alert)

        # Overall stress alert
        if self.overall_stress_level in [StressLevel.ORANGE, StressLevel.RED]:
            alerts.append({
                'metric': 'overall',
                'stress_score': self.overall_stress_score,
                'severity': 'high' if self.overall_stress_level == StressLevel.RED else 'medium',
                'message': f"Overall liquidity stress at {self.overall_stress_level.value.upper()} level",
            })

        return alerts

    def _get_alert_severity(self, score: float) -> str:
        """Get alert severity from score"""
        if score >= 0.80:
            return 'critical'
        elif score >= 0.60:
            return 'high'
        elif score >= 0.40:
            return 'medium'
        else:
            return 'low'

    def _get_alert_message(self, metric: str, score: float) -> str:
        """Generate alert message for metric"""
        value = self.current_metrics.get(metric, 0)

        messages = {
            'ted_spread': f"TED spread at {value:.2f} bps - elevated interbank stress",
            'libor_ois_spread': f"LIBOR-OIS at {value:.2f} bps - bank funding stress",
            'vix': f"VIX at {value:.1f} - elevated equity volatility",
            'move_index': f"MOVE at {value:.1f} - elevated bond volatility",
            'high_yield_spread': f"HY spread at {value:.2f}% - credit stress",
        }

        return messages.get(metric, f"{metric} showing elevated stress")

    def _generate_recommendations(self) -> List[str]:
        """
        Generate trading recommendations based on stress level

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if self.overall_stress_level == StressLevel.RED:
            recommendations.extend([
                "CRITICAL: Reduce all risk positions immediately",
                "Move to cash and safe-haven assets (USD, Treasury bonds, gold)",
                "Avoid new position entries until stress subsides",
                "Consider hedging strategies (protective puts, inverse ETFs)",
                "Monitor intraday for emergency central bank actions",
            ])
        elif self.overall_stress_level == StressLevel.ORANGE:
            recommendations.extend([
                "HIGH STRESS: Reduce position sizes by 30-50%",
                "Tighten stop losses across all positions",
                "Favor quality over risk (blue chips vs small caps)",
                "Increase cash allocation",
                "Avoid leverage and concentrated positions",
            ])
        elif self.overall_stress_level == StressLevel.YELLOW:
            recommendations.extend([
                "ELEVATED STRESS: Monitor positions closely",
                "Reduce position sizes modestly (10-20%)",
                "Review and update risk management parameters",
                "Be selective with new entries",
                "Maintain hedges if in place",
            ])
        else:  # GREEN
            recommendations.extend([
                "NORMAL CONDITIONS: Standard risk management applies",
                "Proceed with normal trading operations",
                "Continue monitoring stress indicators",
            ])

        # Add metric-specific recommendations
        if self.stress_scores.get('high_yield_spread', 0) > 0.60:
            recommendations.append("Credit markets stressed - avoid high-yield exposure")

        if self.stress_scores.get('vix', 0) > 0.60:
            recommendations.append("High volatility - reduce leverage and position sizes")

        return recommendations

    def get_repo_market_status(self) -> Dict:
        """
        Get repo market status

        Repo market stress is early indicator of systemic issues

        Returns:
            Repo market analysis
        """
        overnight = self.current_metrics.get('repo_overnight', 0)
        term = self.current_metrics.get('repo_term', 0)

        # Normal spread is 5-10 bps
        spread = term - overnight

        status = {
            'overnight_rate': overnight,
            'term_rate': term,
            'spread': spread,
            'status': 'normal',
        }

        if spread > 0.50:
            status['status'] = 'elevated'
            status['message'] = "Elevated repo spread indicates funding stress"
        elif spread > 1.00:
            status['status'] = 'stressed'
            status['message'] = "High repo spread - significant funding pressure"

        return status

    def get_summary(self) -> Dict:
        """
        Get summary of liquidity stress analysis

        Returns:
            Summary dictionary
        """
        analysis = self.detect_stress()

        return {
            'timestamp': datetime.now().isoformat(),
            'stress_level': self.overall_stress_level.value,
            'stress_score': self.overall_stress_score,
            'alerts_count': len(analysis.get('alerts', [])),
            'top_concerns': self._get_top_concerns(),
            'repo_status': self.get_repo_market_status(),
        }

    def _get_top_concerns(self) -> List[str]:
        """Get top 3 stress concerns"""
        # Sort metrics by stress score
        sorted_metrics = sorted(
            self.stress_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Return top 3
        concerns = []
        for metric, score in sorted_metrics[:3]:
            if score > 0.30:  # Only include if elevated
                concerns.append(f"{metric}: {score:.2f}")

        return concerns
