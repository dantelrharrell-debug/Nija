"""
Yield Curve AI Modeler
========================

AI-powered yield curve analysis for recession probability and market regime detection.

Features:
- Yield curve inversion detection
- Recession probability modeling
- Steepening/flattening analysis
- AI-powered predictions using historical patterns
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging

from .gmig_config import YIELD_CURVE_CONFIG

logger = logging.getLogger("nija.gmig.yield_curve")


class CurveShape(Enum):
    """Yield curve shapes"""
    NORMAL = "normal"              # Upward sloping
    FLAT = "flat"                  # Relatively flat
    INVERTED = "inverted"          # Downward sloping (recession signal)
    STEEP = "steep"                # Very steep (recovery signal)
    HUMPED = "humped"              # Hump in the middle


class YieldCurveAIModeler:
    """
    AI-powered yield curve analysis and recession probability modeling
    
    Key Functions:
    1. Detect yield curve inversions (2y/10y, 3m/10y)
    2. Calculate recession probability using AI model
    3. Analyze curve steepening/flattening trends
    4. Generate macro regime signals
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Yield Curve AI Modeler
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or YIELD_CURVE_CONFIG
        self.tenors = self.config['tenors']
        self.inversion_threshold = self.config['inversion_threshold']
        self.recession_prob_threshold = self.config['recession_probability_threshold']
        
        # Current curve data
        self.current_yields: Dict[str, float] = {}
        self.curve_history: List[Tuple[datetime, Dict]] = []
        
        # Analysis results
        self.current_shape: CurveShape = CurveShape.NORMAL
        self.recession_probability: float = 0.0
        self.key_spreads: Dict[str, float] = {}
        
        # AI model parameters (simplified - would use trained model in production)
        self.ai_weights = self._initialize_ai_weights()
        
        logger.info("YieldCurveAIModeler initialized")
    
    def analyze_curve(self, yields: Dict[str, float] = None) -> Dict:
        """
        Analyze yield curve and calculate recession probability
        
        Args:
            yields: Dictionary mapping tenors to yields (e.g., {'2Y': 4.5, '10Y': 4.2})
            
        Returns:
            Comprehensive yield curve analysis
        """
        logger.info("Analyzing yield curve...")
        
        # Use provided yields or fetch current data
        if yields:
            self.current_yields = yields
        else:
            self.current_yields = self._fetch_current_yields()
        
        analysis = {
            'timestamp': datetime.now().isoformat(),
            'yields': self.current_yields,
            'spreads': {},
            'shape': None,
            'recession_probability': 0.0,
            'signals': [],
        }
        
        # Calculate key spreads
        spreads = self._calculate_spreads()
        analysis['spreads'] = spreads
        self.key_spreads = spreads
        
        # Determine curve shape
        shape = self._determine_curve_shape(spreads)
        analysis['shape'] = shape.value
        self.current_shape = shape
        
        # Calculate recession probability using AI model
        recession_prob = self._calculate_recession_probability(spreads)
        analysis['recession_probability'] = recession_prob
        self.recession_probability = recession_prob
        
        # Generate trading signals
        signals = self._generate_curve_signals(spreads, shape, recession_prob)
        analysis['signals'] = signals
        
        # Add curve dynamics (steepening/flattening)
        dynamics = self._analyze_curve_dynamics()
        analysis['dynamics'] = dynamics
        
        return analysis
    
    def _fetch_current_yields(self) -> Dict[str, float]:
        """
        Fetch current Treasury yields
        
        In production, would fetch from:
        - Treasury.gov API
        - FRED API
        - Bloomberg
        
        Returns:
            Dictionary mapping tenors to yields
        """
        # Simulated yields for demonstration
        # In production, would fetch real data
        
        simulated_yields = {
            '1M': 5.40,
            '3M': 5.35,
            '6M': 5.30,
            '1Y': 5.20,
            '2Y': 4.90,
            '3Y': 4.75,
            '5Y': 4.60,
            '7Y': 4.55,
            '10Y': 4.50,
            '20Y': 4.70,
            '30Y': 4.75,
        }
        
        return simulated_yields
    
    def _calculate_spreads(self) -> Dict[str, float]:
        """
        Calculate key yield spreads
        
        Returns:
            Dictionary of spreads
        """
        yields = self.current_yields
        spreads = {}
        
        # Most important spreads for recession prediction
        if '2Y' in yields and '10Y' in yields:
            spreads['2y_10y'] = yields['10Y'] - yields['2Y']
        
        if '3M' in yields and '10Y' in yields:
            spreads['3m_10y'] = yields['10Y'] - yields['3M']
        
        if '5Y' in yields and '30Y' in yields:
            spreads['5y_30y'] = yields['30Y'] - yields['5Y']
        
        if '2Y' in yields and '30Y' in yields:
            spreads['2y_30y'] = yields['30Y'] - yields['2Y']
        
        # Short-end spread
        if '3M' in yields and '2Y' in yields:
            spreads['3m_2y'] = yields['2Y'] - yields['3M']
        
        return spreads
    
    def _determine_curve_shape(self, spreads: Dict[str, float]) -> CurveShape:
        """
        Determine overall yield curve shape
        
        Args:
            spreads: Key yield spreads
            
        Returns:
            CurveShape enum
        """
        # Primary indicator: 2y-10y spread
        spread_2y_10y = spreads.get('2y_10y', 0)
        
        if spread_2y_10y < self.inversion_threshold:
            return CurveShape.INVERTED
        elif spread_2y_10y < 0.25:
            return CurveShape.FLAT
        elif spread_2y_10y > 1.50:
            return CurveShape.STEEP
        else:
            # Check for hump (2y higher than both 3m and 10y)
            spread_3m_2y = spreads.get('3m_2y', 0)
            if spread_3m_2y < -0.20 and spread_2y_10y > 0:
                return CurveShape.HUMPED
            else:
                return CurveShape.NORMAL
    
    def _calculate_recession_probability(self, spreads: Dict[str, float]) -> float:
        """
        Calculate recession probability using AI model
        
        This uses historical relationships between yield curve and recessions.
        In production, would use trained ML model (Random Forest, Neural Net, etc.)
        
        Args:
            spreads: Key yield spreads
            
        Returns:
            Recession probability (0 to 1)
        """
        # Simplified AI model using weighted indicators
        # Real implementation would use trained ML model
        
        probability = 0.0
        
        # Factor 1: 2y-10y inversion (strongest predictor)
        spread_2y_10y = spreads.get('2y_10y', 0)
        if spread_2y_10y < -0.50:
            prob_2y10y = 0.80  # Very high probability
        elif spread_2y_10y < 0:
            prob_2y10y = 0.50 + abs(spread_2y_10y) * 0.60  # Scale with inversion depth
        else:
            prob_2y10y = max(0, 0.10 - spread_2y_10y * 0.05)  # Low prob when normal
        
        # Factor 2: 3m-10y spread (leading indicator)
        spread_3m_10y = spreads.get('3m_10y', 0)
        if spread_3m_10y < -0.50:
            prob_3m10y = 0.70
        elif spread_3m_10y < 0:
            prob_3m10y = 0.40 + abs(spread_3m_10y) * 0.60
        else:
            prob_3m10y = max(0, 0.05 - spread_3m_10y * 0.02)
        
        # Factor 3: Curve shape
        if self.current_shape == CurveShape.INVERTED:
            shape_factor = 0.60
        elif self.current_shape == CurveShape.FLAT:
            shape_factor = 0.30
        else:
            shape_factor = 0.05
        
        # Combine factors with weights (from self.ai_weights)
        weights = self.ai_weights
        probability = (
            prob_2y10y * weights['2y_10y'] +
            prob_3m10y * weights['3m_10y'] +
            shape_factor * weights['shape']
        )
        
        # Normalize to [0, 1]
        probability = max(0.0, min(1.0, probability))
        
        return round(probability, 3)
    
    def _initialize_ai_weights(self) -> Dict[str, float]:
        """
        Initialize AI model weights
        
        In production, these would come from trained model
        """
        # Historical analysis shows 2y-10y is strongest predictor
        return {
            '2y_10y': 0.50,
            '3m_10y': 0.30,
            'shape': 0.20,
        }
    
    def _generate_curve_signals(self, spreads: Dict[str, float],
                                shape: CurveShape,
                                recession_prob: float) -> List[Dict]:
        """
        Generate trading signals from yield curve analysis
        
        Args:
            spreads: Key yield spreads
            shape: Curve shape
            recession_prob: Recession probability
            
        Returns:
            List of signal dictionaries
        """
        signals = []
        
        # Signal 1: Inversion warning
        spread_2y_10y = spreads.get('2y_10y', 0)
        if spread_2y_10y < 0:
            signals.append({
                'type': 'yield_curve_inversion',
                'severity': 'high',
                'spread': spread_2y_10y,
                'description': f"2y-10y inverted by {abs(spread_2y_10y):.2f}%",
                'implication': "Strong recession signal - reduce risk exposure",
            })
        
        # Signal 2: High recession probability
        if recession_prob >= self.recession_prob_threshold:
            signals.append({
                'type': 'high_recession_probability',
                'severity': 'high' if recession_prob > 0.60 else 'medium',
                'probability': recession_prob,
                'description': f"Recession probability at {recession_prob:.1%}",
                'implication': "Defensive positioning recommended",
            })
        
        # Signal 3: Curve steepening (recovery signal)
        if shape == CurveShape.STEEP:
            signals.append({
                'type': 'steep_curve',
                'severity': 'low',
                'spread': spread_2y_10y,
                'description': f"Steep curve ({spread_2y_10y:.2f}%)",
                'implication': "Recovery/expansion signal - favorable for risk assets",
            })
        
        # Signal 4: Flattening trend
        dynamics = self._analyze_curve_dynamics()
        if dynamics.get('trend') == 'flattening':
            signals.append({
                'type': 'curve_flattening',
                'severity': 'medium',
                'description': "Yield curve flattening trend",
                'implication': "Late-cycle signal - monitor for inversion",
            })
        
        return signals
    
    def _analyze_curve_dynamics(self) -> Dict:
        """
        Analyze yield curve dynamics (steepening/flattening)
        
        Returns:
            Dictionary with dynamics analysis
        """
        # Would analyze historical changes
        # For now, return simplified analysis
        
        if len(self.curve_history) < 2:
            return {'trend': 'unknown', 'velocity': 0}
        
        # Compare current to recent past
        current_spread = self.key_spreads.get('2y_10y', 0)
        
        # Simulated: would use actual history
        trend = 'stable'
        velocity = 0.0
        
        if current_spread < -0.10:
            trend = 'inverting'
            velocity = -0.05
        elif current_spread > 1.00:
            trend = 'steepening'
            velocity = 0.10
        
        return {
            'trend': trend,
            'velocity': velocity,
            'direction': 'flattening' if velocity < 0 else 'steepening',
        }
    
    def get_recession_timing(self) -> Optional[Dict]:
        """
        Estimate recession timing based on yield curve
        
        Historical pattern: Recession typically occurs 6-24 months after inversion
        
        Returns:
            Dictionary with recession timing estimate or None
        """
        if self.current_shape != CurveShape.INVERTED:
            return None
        
        # Simplified timing model
        # In reality, would use ML model trained on historical inversions
        
        spread_2y_10y = self.key_spreads.get('2y_10y', 0)
        inversion_depth = abs(spread_2y_10y)
        
        # Deeper inversions historically lead to sooner recessions
        if inversion_depth > 0.50:
            timing_months = 6
            confidence = 0.70
        elif inversion_depth > 0.25:
            timing_months = 12
            confidence = 0.60
        else:
            timing_months = 18
            confidence = 0.45
        
        estimated_date = datetime.now() + timedelta(days=30 * timing_months)
        
        return {
            'estimated_months': timing_months,
            'estimated_date': estimated_date.strftime('%Y-%m-%d'),
            'confidence': confidence,
            'inversion_depth': inversion_depth,
        }
    
    def get_summary(self) -> Dict:
        """
        Get summary of yield curve analysis
        
        Returns:
            Summary dictionary
        """
        analysis = self.analyze_curve()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'curve_shape': self.current_shape.value,
            'recession_probability': self.recession_probability,
            'key_spreads': self.key_spreads,
            'signals_count': len(analysis.get('signals', [])),
            'recession_timing': self.get_recession_timing(),
        }
