"""
GMIG Engine - Global Macro Intelligence Grid
==============================================

Main orchestration engine for ultra-advanced macro intelligence.

This is the ULTRA MODE that enables:
- Pre-positioning before macro events
- Asymmetric return opportunities
- Elite-level macro fund capabilities
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

from .gmig_config import GMIG_ENGINE_CONFIG, FUND_GRADE_CONFIG
from .central_bank_monitor import CentralBankMonitor
from .interest_rate_analyzer import InterestRateFuturesAnalyzer
from .yield_curve_modeler import YieldCurveAIModeler
from .liquidity_stress_detector import LiquidityStressDetector
from .crisis_warning_system import CrisisWarningSystem, AlertLevel

logger = logging.getLogger("nija.gmig")


class GMIGEngine:
    """
    Global Macro Intelligence Grid - Ultra Mode

    Orchestrates all macro intelligence components to provide:
    1. Comprehensive macro regime analysis
    2. Crisis early-warning
    3. Pre-positioning signals
    4. Fund-grade reporting
    5. Multi-account capital orchestration

    This is the pinnacle of autonomous trading intelligence.
    """

    def __init__(self, broker_manager=None, config: Dict = None):
        """
        Initialize GMIG Engine

        Args:
            broker_manager: BrokerManager instance (optional)
            config: Optional configuration dictionary
        """
        self.config = config or GMIG_ENGINE_CONFIG
        self.enabled = self.config['enabled']
        self.mode = self.config['mode']
        self.intelligence_level = self.config['intelligence_level']
        self.update_frequency = self.config['update_frequency_minutes']
        self.crisis_check_frequency = self.config['crisis_check_frequency_minutes']

        # Initialize all components
        logger.info("Initializing GMIG components...")

        self.central_bank_monitor = CentralBankMonitor()
        self.interest_rate_analyzer = InterestRateFuturesAnalyzer()
        self.yield_curve_modeler = YieldCurveAIModeler()
        self.liquidity_stress_detector = LiquidityStressDetector()
        self.crisis_warning_system = CrisisWarningSystem()

        # State tracking
        self.last_update: Optional[datetime] = None
        self.last_crisis_check: Optional[datetime] = None
        self.current_macro_regime: str = "unknown"
        self.current_positioning_signal: str = "neutral"
        self.alert_level: AlertLevel = AlertLevel.GREEN

        # Performance tracking
        self.performance_metrics = {
            'total_signals': 0,
            'crisis_warnings': 0,
            'successful_pre_positions': 0,
            'macro_regime_changes': 0,
        }

        # Integration points (CRITICAL)
        from .gmig_integrations import (
            GMIGtoMMINIntegration,
            GMIGtoMetaAIIntegration,
            GMIGtoCapitalEngineIntegration,
        )

        self.mmin_integration = GMIGtoMMINIntegration()
        self.meta_ai_integration = GMIGtoMetaAIIntegration()
        self.capital_integration = GMIGtoCapitalEngineIntegration()

        logger.info(f"GMIGEngine initialized (mode={self.mode}, intelligence={self.intelligence_level})")
        logger.info("✓ Integration points established: MMIN, Meta-AI, Capital Engine")

    def run_full_analysis(self) -> Dict:
        """
        Run comprehensive macro intelligence analysis

        Returns:
            Complete macro intelligence report
        """
        logger.info("=" * 80)
        logger.info("GMIG FULL ANALYSIS STARTING")
        logger.info("=" * 80)

        start_time = datetime.now()

        # 1. Update central bank monitoring
        logger.info("📊 Updating central bank data...")
        central_bank_data = self.central_bank_monitor.update_all_banks()

        # 2. Analyze interest rate expectations
        logger.info("💰 Analyzing interest rate futures...")
        current_rate = central_bank_data.get('FED', {}).get('current_rate', 5.50)
        rate_analysis = self.interest_rate_analyzer.analyze_rate_expectations(current_rate)

        # 3. Analyze yield curve
        logger.info("📈 Analyzing yield curve...")
        yield_curve_analysis = self.yield_curve_modeler.analyze_curve()

        # 4. Detect liquidity stress
        logger.info("💧 Detecting liquidity stress...")
        liquidity_analysis = self.liquidity_stress_detector.detect_stress()

        # 5. Assess crisis risk
        logger.info("🚨 Assessing crisis risk...")
        crisis_assessment = self.crisis_warning_system.assess_crisis_risk(
            yield_curve_data=yield_curve_analysis,
            liquidity_data=liquidity_analysis,
            central_bank_data=central_bank_data,
        )

        # 6. Synthesize macro regime
        logger.info("🧠 Synthesizing macro regime...")
        macro_regime = self._synthesize_macro_regime(
            central_bank_data,
            rate_analysis,
            yield_curve_analysis,
            liquidity_analysis,
            crisis_assessment,
        )

        # 7. Generate positioning signals
        logger.info("🎯 Generating positioning signals...")
        positioning_signals = self._generate_positioning_signals(
            macro_regime,
            crisis_assessment,
            yield_curve_analysis,
            liquidity_analysis,
        )

        # 8. Calculate risk adjustments
        logger.info("⚖️ Calculating risk adjustments...")
        risk_adjustments = self._calculate_risk_adjustments(
            crisis_assessment,
            liquidity_analysis,
        )

        # Update state
        self.last_update = datetime.now()
        self.current_macro_regime = macro_regime['regime']
        self.current_positioning_signal = positioning_signals['primary_signal']
        self.alert_level = crisis_assessment['alert_level']
        self.performance_metrics['total_signals'] += 1

        execution_time = (datetime.now() - start_time).total_seconds()

        # Compile full report
        full_report = {
            'timestamp': datetime.now().isoformat(),
            'execution_time_seconds': execution_time,
            'gmig_version': '1.0.0',
            'intelligence_level': self.intelligence_level,

            # Core analyses
            'central_banks': central_bank_data,
            'interest_rates': rate_analysis,
            'yield_curve': yield_curve_analysis,
            'liquidity_stress': liquidity_analysis,
            'crisis_assessment': crisis_assessment,

            # Synthesized intelligence
            'macro_regime': macro_regime,
            'positioning_signals': positioning_signals,
            'risk_adjustments': risk_adjustments,

            # Summary
            'summary': self._generate_executive_summary(
                macro_regime,
                positioning_signals,
                crisis_assessment,
            ),
        }

        logger.info("=" * 80)
        logger.info(f"GMIG ANALYSIS COMPLETE (took {execution_time:.2f}s)")
        logger.info(f"Regime: {macro_regime['regime']}")
        logger.info(f"Signal: {positioning_signals['primary_signal']}")
        logger.info(f"Alert: {crisis_assessment['alert_level']}")
        logger.info("=" * 80)

        return full_report

    def run_crisis_check(self) -> Dict:
        """
        Run quick crisis check (faster than full analysis)

        Returns:
            Crisis check results
        """
        logger.info("Running quick crisis check...")

        # Quick liquidity check
        liquidity_analysis = self.liquidity_stress_detector.detect_stress()

        # Quick crisis assessment
        crisis_assessment = self.crisis_warning_system.assess_crisis_risk(
            liquidity_data=liquidity_analysis,
        )

        self.last_crisis_check = datetime.now()
        self.alert_level = crisis_assessment['alert_level']

        return {
            'timestamp': datetime.now().isoformat(),
            'alert_level': crisis_assessment['alert_level'],
            'crisis_probability': crisis_assessment['crisis_probability'],
            'stress_level': liquidity_analysis['overall_stress_level'],
            'action_required': crisis_assessment['alert_level'] in ['orange', 'red'],
        }

    def _synthesize_macro_regime(self,
                                 central_bank_data: Dict,
                                 rate_analysis: Dict,
                                 yield_curve_analysis: Dict,
                                 liquidity_analysis: Dict,
                                 crisis_assessment: Dict) -> Dict:
        """
        Synthesize overall macro regime from all components

        Returns:
            Macro regime analysis
        """
        # Determine regime based on multiple factors

        # Factor 1: Central bank policy
        cb_aggregate = central_bank_data.get('aggregate_stance', {})
        cb_stance = cb_aggregate.get('aggregate_stance', 0)

        # Factor 2: Yield curve
        recession_prob = yield_curve_analysis.get('recession_probability', 0)

        # Factor 3: Liquidity conditions
        stress_score = liquidity_analysis.get('overall_stress_score', 0)

        # Factor 4: Crisis probability
        crisis_prob = crisis_assessment.get('crisis_probability', 0)

        # Determine regime
        if crisis_prob > 0.60:
            regime = "crisis"
            description = "Financial crisis conditions"
        elif recession_prob > 0.50:
            regime = "pre_recession"
            description = "Pre-recession environment"
        elif stress_score > 0.60:
            regime = "risk_off"
            description = "Risk-off market regime"
        elif cb_stance > 0.40:
            regime = "tightening"
            description = "Central bank tightening cycle"
        elif cb_stance < -0.40:
            regime = "easing"
            description = "Central bank easing cycle"
        elif stress_score < 0.30 and recession_prob < 0.20:
            regime = "risk_on"
            description = "Risk-on market regime"
        else:
            regime = "transitional"
            description = "Transitional/uncertain regime"

        return {
            'regime': regime,
            'description': description,
            'confidence': self._calculate_regime_confidence(),
            'factors': {
                'central_bank_stance': cb_stance,
                'recession_probability': recession_prob,
                'liquidity_stress': stress_score,
                'crisis_probability': crisis_prob,
            }
        }

    def _calculate_regime_confidence(self) -> float:
        """Calculate confidence in regime assessment"""
        # Would analyze consistency across indicators
        # For now, return high confidence
        return 0.85

    def _generate_positioning_signals(self,
                                     macro_regime: Dict,
                                     crisis_assessment: Dict,
                                     yield_curve_analysis: Dict,
                                     liquidity_analysis: Dict) -> Dict:
        """
        Generate actionable positioning signals

        Returns:
            Positioning signals and recommendations
        """
        regime = macro_regime['regime']
        alert_level = crisis_assessment['alert_level']

        # Determine primary signal
        if alert_level == 'red':
            primary_signal = "maximum_defensive"
            signal_strength = 1.0
        elif alert_level == 'orange':
            primary_signal = "reduce_risk"
            signal_strength = 0.75
        elif regime == "crisis" or regime == "pre_recession":
            primary_signal = "defensive"
            signal_strength = 0.60
        elif regime == "risk_off":
            primary_signal = "cautious"
            signal_strength = 0.40
        elif regime == "risk_on":
            primary_signal = "aggressive"
            signal_strength = 0.70
        elif regime == "easing":
            primary_signal = "bullish"
            signal_strength = 0.60
        else:
            primary_signal = "neutral"
            signal_strength = 0.30

        # Asset class recommendations
        asset_recommendations = self._get_asset_class_recommendations(regime, alert_level)

        # Sector recommendations
        sector_recommendations = self._get_sector_recommendations(regime)

        # Leverage recommendations
        leverage_rec = self._get_leverage_recommendation(alert_level, liquidity_analysis)

        return {
            'primary_signal': primary_signal,
            'signal_strength': signal_strength,
            'regime': regime,
            'asset_classes': asset_recommendations,
            'sectors': sector_recommendations,
            'leverage': leverage_rec,
            'specific_actions': self._get_specific_actions(primary_signal),
        }

    def _get_asset_class_recommendations(self, regime: str, alert_level: str) -> Dict:
        """Get asset class allocation recommendations"""

        recommendations = {
            'crisis': {
                'cash': 0.60,
                'treasuries': 0.30,
                'gold': 0.10,
                'crypto': 0.00,
                'equities': 0.00,
            },
            'pre_recession': {
                'cash': 0.40,
                'treasuries': 0.30,
                'gold': 0.10,
                'crypto': 0.05,
                'equities': 0.15,
            },
            'risk_off': {
                'cash': 0.30,
                'treasuries': 0.20,
                'gold': 0.10,
                'crypto': 0.10,
                'equities': 0.30,
            },
            'tightening': {
                'cash': 0.20,
                'treasuries': 0.20,
                'gold': 0.05,
                'crypto': 0.15,
                'equities': 0.40,
            },
            'easing': {
                'cash': 0.10,
                'treasuries': 0.10,
                'gold': 0.10,
                'crypto': 0.30,
                'equities': 0.40,
            },
            'risk_on': {
                'cash': 0.10,
                'treasuries': 0.05,
                'gold': 0.05,
                'crypto': 0.35,
                'equities': 0.45,
            },
        }

        return recommendations.get(regime, {
            'cash': 0.25,
            'treasuries': 0.25,
            'gold': 0.10,
            'crypto': 0.20,
            'equities': 0.20,
        })

    def _get_sector_recommendations(self, regime: str) -> List[str]:
        """Get sector recommendations"""

        sector_map = {
            'crisis': ['Consumer Staples', 'Healthcare', 'Utilities'],
            'pre_recession': ['Healthcare', 'Consumer Staples', 'Utilities'],
            'risk_off': ['Consumer Staples', 'Healthcare', 'Bonds'],
            'tightening': ['Financials', 'Energy', 'Value'],
            'easing': ['Technology', 'Growth', 'Small Caps'],
            'risk_on': ['Technology', 'Growth', 'Emerging Markets'],
        }

        return sector_map.get(regime, ['Diversified'])

    def _get_leverage_recommendation(self, alert_level: str, liquidity_analysis: Dict) -> Dict:
        """Get leverage recommendations"""

        leverage_map = {
            'red': {'max_leverage': 1.0, 'recommended': 0.0, 'description': 'No leverage - crisis mode'},
            'orange': {'max_leverage': 1.2, 'recommended': 1.0, 'description': 'Minimal leverage only'},
            'yellow': {'max_leverage': 1.5, 'recommended': 1.2, 'description': 'Reduced leverage'},
            'green': {'max_leverage': 2.0, 'recommended': 1.5, 'description': 'Normal leverage acceptable'},
        }

        return leverage_map.get(alert_level, leverage_map['yellow'])

    def _get_specific_actions(self, signal: str) -> List[str]:
        """Get specific action items"""

        actions_map = {
            'maximum_defensive': [
                "Liquidate all speculative positions immediately",
                "Move to 60%+ cash",
                "Hold only safe-haven assets",
                "Activate all hedges",
            ],
            'reduce_risk': [
                "Reduce positions by 50%",
                "Tighten stop losses",
                "Increase cash to 40%",
                "Add defensive hedges",
            ],
            'defensive': [
                "Reduce risk exposure by 30%",
                "Focus on quality assets",
                "Review correlations",
                "Prepare for volatility",
            ],
            'cautious': [
                "Maintain conservative positioning",
                "Monitor closely",
                "Avoid new high-risk trades",
            ],
            'neutral': [
                "Balanced positioning",
                "Normal risk management",
            ],
            'bullish': [
                "Opportunistic long positions",
                "Focus on growth assets",
                "Gradual exposure increase",
            ],
            'aggressive': [
                "Full risk-on positioning",
                "Maximize growth exposure",
                "Utilize momentum strategies",
            ],
        }

        return actions_map.get(signal, ["Maintain current positioning"])

    def _calculate_risk_adjustments(self,
                                   crisis_assessment: Dict,
                                   liquidity_analysis: Dict) -> Dict:
        """
        Calculate recommended risk adjustments

        Returns:
            Risk adjustment recommendations
        """
        alert_level = crisis_assessment['alert_level']
        stress_score = liquidity_analysis.get('overall_stress_score', 0)

        # Position size multiplier
        if alert_level == 'red':
            position_size_multiplier = 0.20
        elif alert_level == 'orange':
            position_size_multiplier = 0.50
        elif alert_level == 'yellow':
            position_size_multiplier = 0.75
        else:
            position_size_multiplier = 1.00

        # Stop loss tightness
        if stress_score > 0.70:
            stop_loss_multiplier = 0.70  # Tighter stops
        elif stress_score > 0.40:
            stop_loss_multiplier = 0.85
        else:
            stop_loss_multiplier = 1.00

        return {
            'position_size_multiplier': position_size_multiplier,
            'stop_loss_multiplier': stop_loss_multiplier,
            'max_portfolio_heat': self._calculate_max_heat(alert_level),
            'recommended_cash_level': self._get_recommended_cash(alert_level),
        }

    def _calculate_max_heat(self, alert_level: str) -> float:
        """Calculate maximum portfolio heat (total risk)"""
        heat_map = {
            'red': 0.02,    # 2% max
            'orange': 0.05,  # 5% max
            'yellow': 0.10,  # 10% max
            'green': 0.20,   # 20% max
        }
        return heat_map.get(alert_level, 0.10)

    def _get_recommended_cash(self, alert_level: str) -> float:
        """Get recommended cash level"""
        cash_map = {
            'red': 0.60,
            'orange': 0.40,
            'yellow': 0.25,
            'green': 0.10,
        }
        return cash_map.get(alert_level, 0.20)

    def _generate_executive_summary(self,
                                   macro_regime: Dict,
                                   positioning_signals: Dict,
                                   crisis_assessment: Dict) -> Dict:
        """Generate executive summary"""

        return {
            'macro_regime': macro_regime['regime'],
            'regime_description': macro_regime['description'],
            'positioning_signal': positioning_signals['primary_signal'],
            'signal_strength': positioning_signals['signal_strength'],
            'alert_level': crisis_assessment['alert_level'],
            'crisis_probability': crisis_assessment['crisis_probability'],
            'key_recommendation': self._get_key_recommendation(positioning_signals),
            'risk_level': self._assess_overall_risk(crisis_assessment),
        }

    def _get_key_recommendation(self, signals: Dict) -> str:
        """Get single key recommendation"""
        signal = signals['primary_signal']

        rec_map = {
            'maximum_defensive': "EMERGENCY: Move to maximum defensive positioning immediately",
            'reduce_risk': "Significantly reduce risk exposure across all positions",
            'defensive': "Adopt defensive positioning and increase cash reserves",
            'cautious': "Maintain cautious stance with conservative exposure",
            'neutral': "Balanced approach with normal risk management",
            'bullish': "Opportunistic positioning for upside potential",
            'aggressive': "Full risk-on exposure to capitalize on favorable conditions",
        }

        return rec_map.get(signal, "Maintain current positioning")

    def _assess_overall_risk(self, crisis_assessment: Dict) -> str:
        """Assess overall market risk level"""
        crisis_prob = crisis_assessment['crisis_probability']

        if crisis_prob > 0.70:
            return "EXTREME"
        elif crisis_prob > 0.50:
            return "HIGH"
        elif crisis_prob > 0.30:
            return "ELEVATED"
        else:
            return "MODERATE"

    def get_integration_parameters(self, target_system: str) -> Dict:
        """
        Get integration parameters for downstream systems

        Args:
            target_system: 'mmin', 'meta_ai', or 'capital_engine'

        Returns:
            Integration parameters for the target system
        """
        # Get current GMIG state
        if self.last_update is None:
            logger.warning("No GMIG analysis available - running quick analysis")
            self.run_crisis_check()

        gmig_state = {
            'macro_regime': self.current_macro_regime,
            'alert_level': self.alert_level,
            'positioning_signal': self.current_positioning_signal,
            'crisis_probability': 0.0,  # Would be from last analysis
            'liquidity_stress_level': 'green',  # Would be from last analysis
            'asset_classes': {},  # Would be from last analysis
            'risk_adjustments': {},  # Would be from last analysis
        }

        if target_system == 'mmin':
            return {
                'signal_filters_active': True,
                'allocation_weights_method': 'gmig_regime_based',
                'correlation_gating_enabled': True,
                'gmig_state': gmig_state,
            }

        elif target_system == 'meta_ai':
            mutation_bias = self.meta_ai_integration.calculate_mutation_bias(gmig_state)
            fitness_weights = self.meta_ai_integration.calculate_fitness_weights(gmig_state)
            evolution_pressure = self.meta_ai_integration.get_regime_evolution_pressure(gmig_state)

            return {
                'mutation_bias': mutation_bias,
                'fitness_weights': fitness_weights,
                'evolution_pressure': evolution_pressure,
                'gmig_state': gmig_state,
            }

        elif target_system == 'capital_engine':
            leverage_limits = self.capital_integration.calculate_leverage_limits(gmig_state)
            position_caps = self.capital_integration.calculate_position_size_caps(10000, gmig_state)  # Example balance
            circuit_breakers = self.capital_integration.get_drawdown_circuit_breakers(gmig_state)
            heat_limits = self.capital_integration.get_portfolio_heat_limits(gmig_state)

            return {
                'leverage_limits': leverage_limits,
                'position_size_caps': position_caps,
                'circuit_breakers': circuit_breakers,
                'heat_limits': heat_limits,
                'gmig_state': gmig_state,
            }

        else:
            raise ValueError(f"Unknown target system: {target_system}")

    def get_summary(self) -> Dict:
        """Get GMIG summary"""
        return {
            'timestamp': datetime.now().isoformat(),
            'enabled': self.enabled,
            'mode': self.mode,
            'intelligence_level': self.intelligence_level,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'current_regime': self.current_macro_regime,
            'current_signal': self.current_positioning_signal,
            'alert_level': self.alert_level.value if hasattr(self.alert_level, 'value') else self.alert_level,
            'performance_metrics': self.performance_metrics,
            'integration_points': ['MMIN', 'Meta-AI', 'Capital Engine'],
        }
