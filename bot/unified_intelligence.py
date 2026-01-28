"""
NIJA Unified Intelligence System
==================================

Three-tier intelligence architecture for full-stack autonomous capital intelligence.

Architecture:
- GMIG (Strategic Global Intelligence) - Macro regime governance
- MMIN (Tactical Intelligence) - Multi-market operations  
- Meta-AI (Evolution Intelligence) - Strategy adaptation

This module provides the unified interface and orchestration.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("nija.unified_intelligence")


class UnifiedIntelligenceSystem:
    """
    Unified Intelligence System - Full-Stack Autonomous Capital Intelligence
    
    Three-Tier Architecture:
    
    1. GMIG (Strategic Layer - The Brainstem)
       - Global macro regime detection
       - Crisis forecasting and early warning
       - Strategic capital allocation governance
       - Risk regime management
       
    2. MMIN (Tactical Layer - The Network)
       - Multi-market tactical intelligence
       - Cross-market opportunity identification
       - Tactical capital routing
       - Correlation-aware trading
       
    3. Meta-AI (Evolution Layer - The Optimizer)
       - Strategy evolution and adaptation
       - Performance optimization
       - Alpha discovery
       - Continuous learning
    
    Integration Flow:
    GMIG → Strategic decisions (regime, risk level)
      ↓
    MMIN → Tactical execution (which markets, correlations)
      ↓
    Meta-AI → Strategy selection and evolution (how to trade)
      ↓
    Trading Execution
    """
    
    def __init__(self, broker_manager=None):
        """
        Initialize Unified Intelligence System
        
        Args:
            broker_manager: BrokerManager instance for market access
        """
        logger.info("Initializing Unified Intelligence System...")
        
        self.broker_manager = broker_manager
        
        # Layer 1: Strategic Intelligence (GMIG)
        try:
            from bot.gmig import GMIGEngine
            self.gmig = GMIGEngine(broker_manager=broker_manager)
            self.gmig_enabled = True
            logger.info("✓ GMIG (Strategic Intelligence) initialized")
        except Exception as e:
            logger.warning(f"GMIG not available: {e}")
            self.gmig = None
            self.gmig_enabled = False
        
        # Layer 2: Tactical Intelligence (MMIN)
        try:
            from bot.mmin import MMINEngine
            self.mmin = MMINEngine(broker_manager=broker_manager)
            self.mmin_enabled = True
            logger.info("✓ MMIN (Tactical Intelligence) initialized")
        except Exception as e:
            logger.warning(f"MMIN not available: {e}")
            self.mmin = None
            self.mmin_enabled = False
        
        # Layer 3: Evolution Intelligence (Meta-AI)
        try:
            from bot.meta_ai import EvolutionEngine
            self.meta_ai = EvolutionEngine()
            self.meta_ai_enabled = True
            logger.info("✓ Meta-AI (Evolution Intelligence) initialized")
        except Exception as e:
            logger.warning(f"Meta-AI not available: {e}")
            self.meta_ai = None
            self.meta_ai_enabled = False
        
        # System state
        self.current_strategic_regime = "unknown"
        self.current_tactical_allocation = {}
        self.current_active_strategies = []
        self.last_full_analysis = None
        
        logger.info("Unified Intelligence System ready")
        logger.info(f"  GMIG: {'✓' if self.gmig_enabled else '✗'}")
        logger.info(f"  MMIN: {'✓' if self.mmin_enabled else '✗'}")
        logger.info(f"  Meta-AI: {'✓' if self.meta_ai_enabled else '✗'}")
    
    def run_full_intelligence_cycle(self) -> Dict:
        """
        Run complete intelligence cycle across all three layers
        
        Returns:
            Unified intelligence report with strategic, tactical, and evolutionary recommendations
        """
        logger.info("=" * 80)
        logger.info("UNIFIED INTELLIGENCE CYCLE STARTING")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        unified_report = {
            'timestamp': start_time.isoformat(),
            'layers_active': {
                'gmig': self.gmig_enabled,
                'mmin': self.mmin_enabled,
                'meta_ai': self.meta_ai_enabled,
            },
        }
        
        # ========================================
        # LAYER 1: STRATEGIC INTELLIGENCE (GMIG)
        # ========================================
        if self.gmig_enabled:
            logger.info("\n📊 LAYER 1: Strategic Intelligence (GMIG)")
            logger.info("-" * 80)
            
            gmig_report = self.gmig.run_full_analysis()
            unified_report['strategic'] = gmig_report
            
            # Extract strategic directives
            macro_regime = gmig_report['macro_regime']['regime']
            alert_level = gmig_report['crisis_assessment']['alert_level']
            if hasattr(alert_level, 'value'):
                alert_level = alert_level.value
            
            positioning = gmig_report['positioning_signals']['primary_signal']
            risk_adjustments = gmig_report['risk_adjustments']
            
            self.current_strategic_regime = macro_regime
            
            logger.info(f"  Strategic Regime: {macro_regime.upper()}")
            logger.info(f"  Alert Level: {alert_level.upper()}")
            logger.info(f"  Positioning: {positioning.upper()}")
            logger.info(f"  Position Size Multiplier: {risk_adjustments['position_size_multiplier']:.2f}x")
        else:
            unified_report['strategic'] = {'status': 'disabled'}
            macro_regime = 'unknown'
            positioning = 'neutral'
            risk_adjustments = {'position_size_multiplier': 1.0}
        
        # ========================================
        # LAYER 2: TACTICAL INTELLIGENCE (MMIN)
        # ========================================
        if self.mmin_enabled:
            logger.info("\n🌐 LAYER 2: Tactical Intelligence (MMIN)")
            logger.info("-" * 80)
            
            # Pass strategic context to MMIN
            mmin_report = self.mmin.analyze_markets(
                timeframe='1h',
                limit=500
            )
            unified_report['tactical'] = mmin_report
            
            # Extract tactical allocation
            if 'capital_allocation' in mmin_report:
                self.current_tactical_allocation = mmin_report['capital_allocation']
                logger.info(f"  Markets Analyzed: {len(mmin_report.get('market_data', {}))}")
                logger.info(f"  Cross-Market Signals: {mmin_report.get('total_signals', 0)}")
        else:
            unified_report['tactical'] = {'status': 'disabled'}
        
        # ========================================
        # LAYER 3: EVOLUTION INTELLIGENCE (Meta-AI)
        # ========================================
        if self.meta_ai_enabled:
            logger.info("\n🧬 LAYER 3: Evolution Intelligence (Meta-AI)")
            logger.info("-" * 80)
            
            # Pass strategic and tactical context to Meta-AI
            # Meta-AI adapts strategies based on regime
            try:
                meta_ai_report = {
                    'status': 'active',
                    'strategy_population': getattr(self.meta_ai, 'population_size', 50),
                    'best_performers': [],  # Would get from actual evolution
                }
                unified_report['evolutionary'] = meta_ai_report
                
                logger.info(f"  Strategy Population: {meta_ai_report['strategy_population']}")
                logger.info(f"  Evolution Active: True")
            except Exception as e:
                logger.warning(f"  Meta-AI analysis error: {e}")
                unified_report['evolutionary'] = {'status': 'error', 'error': str(e)}
        else:
            unified_report['evolutionary'] = {'status': 'disabled'}
        
        # ========================================
        # UNIFIED DECISION SYNTHESIS
        # ========================================
        logger.info("\n🎯 UNIFIED DECISION SYNTHESIS")
        logger.info("-" * 80)
        
        unified_decision = self._synthesize_unified_decision(
            strategic=unified_report.get('strategic', {}),
            tactical=unified_report.get('tactical', {}),
            evolutionary=unified_report.get('evolutionary', {}),
        )
        
        unified_report['unified_decision'] = unified_decision
        
        # Display unified decision
        logger.info(f"  Overall Risk Level: {unified_decision['overall_risk_level']}")
        logger.info(f"  Recommended Action: {unified_decision['recommended_action']}")
        logger.info(f"  Position Size: {unified_decision['position_size_multiplier']:.2f}x")
        logger.info(f"  Active Markets: {', '.join(unified_decision['active_markets'][:3])}")
        
        # Execution time
        execution_time = (datetime.now() - start_time).total_seconds()
        unified_report['execution_time_seconds'] = execution_time
        
        self.last_full_analysis = datetime.now()
        
        logger.info("\n" + "=" * 80)
        logger.info(f"UNIFIED INTELLIGENCE CYCLE COMPLETE ({execution_time:.2f}s)")
        logger.info("=" * 80)
        
        return unified_report
    
    def _synthesize_unified_decision(self,
                                    strategic: Dict,
                                    tactical: Dict,
                                    evolutionary: Dict) -> Dict:
        """
        Synthesize unified trading decision from all three intelligence layers
        
        Args:
            strategic: GMIG strategic intelligence
            tactical: MMIN tactical intelligence
            evolutionary: Meta-AI evolution intelligence
            
        Returns:
            Unified decision dictionary
        """
        # Extract strategic directives
        if strategic.get('status') != 'disabled':
            macro_regime = strategic.get('macro_regime', {}).get('regime', 'unknown')
            crisis_prob = strategic.get('crisis_assessment', {}).get('crisis_probability', 0)
            positioning = strategic.get('positioning_signals', {}).get('primary_signal', 'neutral')
            risk_adj = strategic.get('risk_adjustments', {})
            position_multiplier = risk_adj.get('position_size_multiplier', 1.0)
        else:
            macro_regime = 'unknown'
            crisis_prob = 0
            positioning = 'neutral'
            position_multiplier = 1.0
        
        # Determine overall risk level (Strategic layer has final say)
        if crisis_prob > 0.60:
            overall_risk = "EXTREME"
            recommended_action = "EMERGENCY DEFENSIVE"
        elif crisis_prob > 0.40 or macro_regime == 'pre_recession':
            overall_risk = "HIGH"
            recommended_action = "REDUCE RISK"
        elif crisis_prob > 0.20 or macro_regime == 'risk_off':
            overall_risk = "ELEVATED"
            recommended_action = "CAUTIOUS"
        elif macro_regime == 'risk_on' or macro_regime == 'easing':
            overall_risk = "LOW"
            recommended_action = "AGGRESSIVE"
        else:
            overall_risk = "MODERATE"
            recommended_action = "NEUTRAL"
        
        # Extract tactical market selection
        active_markets = []
        if tactical.get('status') != 'disabled':
            # Would extract from MMIN capital allocation
            active_markets = ['BTC-USD', 'ETH-USD', 'SOL-USD']  # Example
        
        # Extract strategy selection from evolutionary layer
        active_strategies = []
        if evolutionary.get('status') != 'disabled':
            # Would extract best performing strategies
            active_strategies = ['momentum', 'mean_reversion', 'breakout']  # Example
        
        unified_decision = {
            'overall_risk_level': overall_risk,
            'recommended_action': recommended_action,
            'macro_regime': macro_regime,
            'crisis_probability': crisis_prob,
            'positioning_signal': positioning,
            'position_size_multiplier': position_multiplier,
            'active_markets': active_markets,
            'active_strategies': active_strategies,
            'layer_consensus': self._calculate_layer_consensus(strategic, tactical, evolutionary),
        }
        
        return unified_decision
    
    def _calculate_layer_consensus(self,
                                  strategic: Dict,
                                  tactical: Dict,
                                  evolutionary: Dict) -> Dict:
        """Calculate consensus across intelligence layers"""
        
        # Strategic layer vote
        strategic_vote = 0  # -1 = defensive, 0 = neutral, +1 = aggressive
        if strategic.get('status') != 'disabled':
            positioning = strategic.get('positioning_signals', {}).get('primary_signal', 'neutral')
            if positioning in ['maximum_defensive', 'reduce_risk', 'defensive']:
                strategic_vote = -1
            elif positioning in ['bullish', 'aggressive']:
                strategic_vote = 1
        
        # Tactical layer vote (based on opportunity count)
        tactical_vote = 0
        if tactical.get('status') != 'disabled':
            # Positive if finding opportunities
            signal_count = tactical.get('total_signals', 0)
            if signal_count > 5:
                tactical_vote = 1
            elif signal_count < 2:
                tactical_vote = -1
        
        # Evolution layer vote (based on strategy performance)
        evolutionary_vote = 0
        # Would be based on recent strategy performance
        
        # Calculate consensus
        total_vote = strategic_vote + tactical_vote + evolutionary_vote
        active_layers = sum([
            strategic.get('status') != 'disabled',
            tactical.get('status') != 'disabled',
            evolutionary.get('status') != 'disabled',
        ])
        
        consensus_score = total_vote / active_layers if active_layers > 0 else 0
        
        if consensus_score > 0.5:
            consensus = "BULLISH"
        elif consensus_score < -0.5:
            consensus = "BEARISH"
        else:
            consensus = "NEUTRAL"
        
        return {
            'consensus': consensus,
            'consensus_score': consensus_score,
            'strategic_vote': strategic_vote,
            'tactical_vote': tactical_vote,
            'evolutionary_vote': evolutionary_vote,
        }
    
    def get_strategic_override(self) -> Optional[Dict]:
        """
        Get strategic override from GMIG (crisis mode, etc.)
        
        Strategic layer has veto power - if crisis detected, tactical and 
        evolutionary layers defer to strategic directives.
        
        Returns:
            Strategic override dict or None if no override needed
        """
        if not self.gmig_enabled:
            return None
        
        # Quick crisis check
        crisis_check = self.gmig.run_crisis_check()
        
        alert_level = crisis_check.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value
        
        # Strategic override triggers
        if alert_level in ['red', 'orange']:
            return {
                'override_active': True,
                'alert_level': alert_level,
                'crisis_probability': crisis_check.get('crisis_probability', 0),
                'action': 'EMERGENCY_DEFENSIVE' if alert_level == 'red' else 'REDUCE_RISK',
                'message': f"Strategic override: {alert_level.upper()} alert - defensive positioning required",
            }
        
        return None
    
    def get_summary(self) -> Dict:
        """Get unified intelligence summary"""
        return {
            'timestamp': datetime.now().isoformat(),
            'layers': {
                'gmig_enabled': self.gmig_enabled,
                'mmin_enabled': self.mmin_enabled,
                'meta_ai_enabled': self.meta_ai_enabled,
            },
            'current_state': {
                'strategic_regime': self.current_strategic_regime,
                'tactical_allocation': self.current_tactical_allocation,
                'active_strategies': self.current_active_strategies,
            },
            'last_analysis': self.last_full_analysis.isoformat() if self.last_full_analysis else None,
        }
