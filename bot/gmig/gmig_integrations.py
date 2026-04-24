"""
GMIG Integration Points
========================

Critical integration points where GMIG (Strategic Intelligence) governs:
- MMIN (Tactical Intelligence)
- Meta-AI (Evolution Intelligence)
- Capital Engine (Execution Layer)

GMIG acts as the strategic brainstem, modulating all downstream systems
based on macro regime and crisis detection.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("nija.gmig.integrations")


class GMIGtoMMINIntegration:
    """
    GMIG → MMIN Integration

    Strategic intelligence feeds into tactical multi-market operations:
    1. Cross-market signal filters (reduce noise in crisis)
    2. Allocation weighting (favor safe havens in risk-off)
    3. Correlation gating (block correlated positions in stress)
    """

    def __init__(self):
        self.current_regime = "unknown"
        self.crisis_level = "green"
        logger.info("GMIG→MMIN Integration initialized")

    def apply_signal_filters(self,
                            signals: List[Dict],
                            gmig_state: Dict) -> List[Dict]:
        """
        Filter MMIN cross-market signals based on GMIG strategic state

        Args:
            signals: Raw signals from MMIN
            gmig_state: Current GMIG strategic state

        Returns:
            Filtered signals
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        crisis_prob = gmig_state.get('crisis_probability', 0)

        filtered_signals = []

        for signal in signals:
            # Crisis mode: Only allow safe-haven signals
            if alert_level == 'red':
                if signal.get('asset_class') in ['cash', 'treasuries', 'gold']:
                    signal['gmig_approved'] = True
                    signal['gmig_reason'] = 'Crisis mode - safe haven only'
                    filtered_signals.append(signal)
                else:
                    logger.debug(f"Filtered signal {signal.get('symbol')}: Crisis mode")
                continue

            # High risk: Reduce speculative signals
            if alert_level == 'orange' or regime == 'pre_recession':
                if signal.get('signal_type') == 'speculative':
                    if 'strength' in signal:
                        signal['strength'] *= 0.5  # Reduce strength
                    signal['gmig_adjustment'] = 'Reduced 50% - high risk regime'
                elif signal.get('asset_class') in ['crypto', 'small_caps']:
                    if 'position_size' in signal:
                        signal['position_size'] *= 0.5
                    signal['gmig_adjustment'] = 'Position size halved - risk reduction'

            # Risk-on: Amplify growth signals
            if regime == 'risk_on' or regime == 'easing':
                if signal.get('asset_class') in ['crypto', 'growth', 'equities']:
                    if 'strength' in signal:
                        signal['strength'] *= 1.3  # Amplify
                        signal['gmig_adjustment'] = 'Amplified 30% - favorable regime'
                    else:
                        signal['gmig_adjustment'] = 'Favorable regime - risk-on'

            signal['gmig_approved'] = True
            signal['gmig_regime'] = regime
            filtered_signals.append(signal)

        logger.info(f"MMIN signals filtered: {len(signals)} → {len(filtered_signals)} (regime: {regime})")
        return filtered_signals

    def calculate_allocation_weights(self,
                                    markets: List[str],
                                    gmig_state: Dict) -> Dict[str, float]:
        """
        Calculate allocation weights based on GMIG strategic regime

        Args:
            markets: List of market symbols
            gmig_state: Current GMIG strategic state

        Returns:
            Dictionary mapping markets to allocation weights
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        # Get GMIG recommended asset allocation
        asset_allocation = gmig_state.get('asset_classes', {})

        weights = {}

        for market in markets:
            # Classify market into asset class
            asset_class = self._classify_market(market)

            # Get base weight from GMIG regime
            base_weight = asset_allocation.get(asset_class, 0.20)

            # Apply crisis adjustments
            if alert_level == 'red':
                if asset_class in ['cash', 'treasuries', 'gold']:
                    weight = base_weight * 2.0  # Double safe havens
                else:
                    weight = 0.0  # Zero risk assets
            elif alert_level == 'orange':
                if asset_class in ['cash', 'treasuries', 'gold']:
                    weight = base_weight * 1.5
                else:
                    weight = base_weight * 0.5
            else:
                weight = base_weight

            weights[market] = weight

        # Normalize weights to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}

        return weights

    def apply_correlation_gating(self,
                                positions: List[Dict],
                                gmig_state: Dict) -> List[Dict]:
        """
        Gate correlated positions during stress periods

        In crisis/stress, correlated positions amplify risk.
        Block new correlated positions when stress is elevated.

        Args:
            positions: Proposed positions
            gmig_state: Current GMIG strategic state

        Returns:
            Gated positions (may be filtered)
        """
        stress_level = gmig_state.get('liquidity_stress_level', 'green')
        if hasattr(stress_level, 'value'):
            stress_level = stress_level.value

        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        # Normal conditions: no gating
        if stress_level == 'green' and alert_level == 'green':
            return positions

        # High stress: Block highly correlated positions
        gated_positions = []
        existing_assets = set()

        for position in positions:
            asset_class = self._classify_market(position.get('symbol', ''))

            # In high stress, limit to one position per asset class
            if stress_level in ['orange', 'red'] or alert_level in ['orange', 'red']:
                if asset_class in existing_assets:
                    logger.info(f"Correlation gate blocked: {position.get('symbol')} (duplicate asset class in stress)")
                    continue

            existing_assets.add(asset_class)
            gated_positions.append(position)

        logger.info(f"Correlation gating: {len(positions)} → {len(gated_positions)}")
        return gated_positions

    def _classify_market(self, symbol: str) -> str:
        """Classify market symbol into asset class"""
        symbol_upper = symbol.upper()

        if 'BTC' in symbol_upper or 'ETH' in symbol_upper or 'SOL' in symbol_upper:
            return 'crypto'
        elif 'USD' in symbol_upper and symbol_upper.startswith('T'):
            return 'treasuries'
        elif 'GLD' in symbol_upper or 'GOLD' in symbol_upper:
            return 'gold'
        elif any(x in symbol_upper for x in ['SPY', 'QQQ', 'AAPL', 'MSFT']):
            return 'equities'
        else:
            return 'other'


class GMIGtoMetaAIIntegration:
    """
    GMIG → Meta-AI Integration

    Strategic intelligence governs strategy evolution:
    1. Strategy mutation bias (adapt to regime)
    2. Fitness weighting (reward regime-appropriate strategies)
    3. Regime-conditioned evolution (different selection pressure by regime)
    """

    def __init__(self):
        logger.info("GMIG→Meta-AI Integration initialized")

    def calculate_mutation_bias(self, gmig_state: Dict) -> Dict[str, float]:
        """
        Calculate mutation bias for strategy evolution based on regime

        Different regimes favor different strategy characteristics:
        - Crisis: Conservative, defensive mutations
        - Risk-on: Aggressive, momentum mutations
        - Transitional: Balanced mutations

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Mutation bias parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        crisis_prob = gmig_state.get('crisis_probability', 0)

        # Base mutation rates
        mutation_bias = {
            'aggression': 0.5,          # How aggressive strategies should be
            'mean_reversion_bias': 0.5,  # Favor mean reversion vs momentum
            'holding_period': 5.0,       # Average holding period in hours
            'stop_loss_tightness': 0.5,  # How tight stop losses should be
            'take_profit_ratio': 2.0,    # Risk:reward ratio
        }

        # Regime-specific biases
        if regime == 'crisis' or crisis_prob > 0.60:
            # Crisis: Ultra-defensive
            mutation_bias['aggression'] = 0.1
            mutation_bias['mean_reversion_bias'] = 0.8  # Favor mean reversion
            mutation_bias['holding_period'] = 2.0       # Shorter holds
            mutation_bias['stop_loss_tightness'] = 0.9  # Very tight stops
            mutation_bias['take_profit_ratio'] = 1.5    # Take profits quickly

        elif regime == 'pre_recession':
            # Pre-recession: Defensive
            mutation_bias['aggression'] = 0.3
            mutation_bias['mean_reversion_bias'] = 0.7
            mutation_bias['holding_period'] = 3.0
            mutation_bias['stop_loss_tightness'] = 0.7
            mutation_bias['take_profit_ratio'] = 1.8

        elif regime == 'risk_off':
            # Risk-off: Cautious
            mutation_bias['aggression'] = 0.4
            mutation_bias['mean_reversion_bias'] = 0.6
            mutation_bias['holding_period'] = 4.0
            mutation_bias['stop_loss_tightness'] = 0.6

        elif regime == 'risk_on':
            # Risk-on: Aggressive
            mutation_bias['aggression'] = 0.8
            mutation_bias['mean_reversion_bias'] = 0.2  # Favor momentum
            mutation_bias['holding_period'] = 8.0       # Longer holds
            mutation_bias['stop_loss_tightness'] = 0.3  # Wider stops
            mutation_bias['take_profit_ratio'] = 3.0    # Let winners run

        elif regime == 'easing':
            # Easing: Bullish
            mutation_bias['aggression'] = 0.7
            mutation_bias['mean_reversion_bias'] = 0.3
            mutation_bias['holding_period'] = 10.0
            mutation_bias['stop_loss_tightness'] = 0.4
            mutation_bias['take_profit_ratio'] = 3.5

        logger.info(f"Mutation bias set for regime '{regime}': aggression={mutation_bias['aggression']:.2f}")
        return mutation_bias

    def calculate_fitness_weights(self, gmig_state: Dict) -> Dict[str, float]:
        """
        Calculate fitness weighting for strategy evaluation

        Rewards strategies that perform well in current regime.

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Fitness weight parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')

        # Base weights (all equal)
        fitness_weights = {
            'total_return': 0.25,
            'sharpe_ratio': 0.25,
            'max_drawdown': 0.25,
            'win_rate': 0.25,
        }

        # Regime-specific fitness priorities
        if regime in ['crisis', 'pre_recession']:
            # Crisis: Prioritize drawdown protection
            fitness_weights = {
                'total_return': 0.10,
                'sharpe_ratio': 0.20,
                'max_drawdown': 0.50,  # Most important
                'win_rate': 0.20,
            }

        elif regime == 'risk_off':
            # Risk-off: Balance safety and returns
            fitness_weights = {
                'total_return': 0.20,
                'sharpe_ratio': 0.30,
                'max_drawdown': 0.35,
                'win_rate': 0.15,
            }

        elif regime in ['risk_on', 'easing']:
            # Risk-on: Prioritize returns
            fitness_weights = {
                'total_return': 0.40,  # Most important
                'sharpe_ratio': 0.30,
                'max_drawdown': 0.15,
                'win_rate': 0.15,
            }

        logger.info(f"Fitness weights set for regime '{regime}'")
        return fitness_weights

    def get_regime_evolution_pressure(self, gmig_state: Dict) -> Dict:
        """
        Get evolution pressure parameters based on regime

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Evolution pressure parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        crisis_prob = gmig_state.get('crisis_probability', 0)

        # Default evolution parameters
        evolution_params = {
            'selection_pressure': 0.5,    # 0 = no pressure, 1 = extreme pressure
            'mutation_rate': 0.1,          # 10% mutation rate
            'crossover_rate': 0.7,         # 70% crossover rate
            'elitism_count': 5,            # Keep top 5 strategies
            'population_diversity': 0.5,   # Maintain 50% diversity
        }

        # High crisis: Strong selection pressure, low diversity
        if crisis_prob > 0.60 or regime == 'crisis':
            evolution_params['selection_pressure'] = 0.9  # Strong pressure
            evolution_params['mutation_rate'] = 0.05      # Low mutation
            evolution_params['elitism_count'] = 10        # Keep more elites
            evolution_params['population_diversity'] = 0.2  # Focus on winners

        # Risk-on: Explore more, less pressure
        elif regime == 'risk_on':
            evolution_params['selection_pressure'] = 0.3  # Low pressure
            evolution_params['mutation_rate'] = 0.15     # Higher mutation
            evolution_params['population_diversity'] = 0.7  # More diversity

        return evolution_params


class GMIGtoCapitalEngineIntegration:
    """
    GMIG → Capital Engine Integration

    Strategic intelligence governs capital deployment:
    1. Leverage scaling (reduce in crisis)
    2. Position sizing caps (tighter in stress)
    3. Drawdown circuit breakers (regime-dependent thresholds)
    """

    def __init__(self):
        # Import here to avoid circular imports
        from .safety_guardrails import get_safety_guardrails
        self.safety = get_safety_guardrails()
        logger.info("GMIG→Capital Engine Integration initialized")
        logger.info("🛡️ Safety Guardrails: ACTIVE")

    def calculate_leverage_limits(self, gmig_state: Dict) -> Dict[str, float]:
        """
        Calculate leverage limits based on GMIG strategic state

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Leverage limit parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        crisis_prob = gmig_state.get('crisis_probability', 0)

        # Alert-level based limits (strategic override)
        if alert_level == 'red':
            max_leverage = 1.0   # No leverage in crisis
            recommended_leverage = 0.0
        elif alert_level == 'orange':
            max_leverage = 1.2
            recommended_leverage = 1.0
        elif alert_level == 'yellow':
            max_leverage = 1.5
            recommended_leverage = 1.2
        else:
            # Regime-based limits
            leverage_by_regime = {
                'crisis': (1.0, 0.0),
                'pre_recession': (1.2, 1.0),
                'risk_off': (1.5, 1.2),
                'tightening': (1.8, 1.5),
                'transitional': (1.5, 1.3),
                'easing': (2.0, 1.7),
                'risk_on': (2.5, 2.0),
            }
            max_leverage, recommended_leverage = leverage_by_regime.get(regime, (1.5, 1.2))

        proposed = {
            'max_leverage': max_leverage,
            'recommended_leverage': recommended_leverage,
            'regime': regime,
            'alert_level': alert_level,
            'leverage_reason': f"Regime: {regime}, Alert: {alert_level}",
        }

        # SAFETY: Enforce conservative limits
        return self.safety.enforce_leverage_limits(proposed, regime)

    def calculate_position_size_caps(self,
                                    account_balance: float,
                                    gmig_state: Dict) -> Dict[str, float]:
        """
        Calculate position size caps based on strategic state

        Args:
            account_balance: Current account balance
            gmig_state: Current GMIG strategic state

        Returns:
            Position sizing parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        stress_level = gmig_state.get('liquidity_stress_level', 'green')
        if hasattr(stress_level, 'value'):
            stress_level = stress_level.value

        # Base position size caps (as % of account)
        if alert_level == 'red' or stress_level == 'red':
            max_position_pct = 0.02      # 2% max per position
            max_total_exposure = 0.20    # 20% max total
        elif alert_level == 'orange' or stress_level == 'orange':
            max_position_pct = 0.05      # 5% max per position
            max_total_exposure = 0.50    # 50% max total
        elif alert_level == 'yellow' or stress_level == 'yellow':
            max_position_pct = 0.10      # 10% max per position
            max_total_exposure = 0.75    # 75% max total
        else:
            # Normal regime-based caps
            regime_caps = {
                'crisis': (0.02, 0.20),
                'pre_recession': (0.05, 0.50),
                'risk_off': (0.08, 0.70),
                'tightening': (0.10, 0.80),
                'transitional': (0.10, 0.75),
                'easing': (0.15, 1.00),
                'risk_on': (0.20, 1.20),
            }
            max_position_pct, max_total_exposure = regime_caps.get(regime, (0.10, 0.75))

        proposed = {
            'max_position_size_usd': account_balance * max_position_pct,
            'max_position_pct': max_position_pct,
            'max_total_exposure_usd': account_balance * max_total_exposure,
            'max_total_exposure_pct': max_total_exposure,
            'regime': regime,
            'alert_level': alert_level,
            'stress_level': stress_level,
        }

        # SAFETY: Enforce conservative caps
        return self.safety.enforce_position_caps(proposed, regime, account_balance)

    def get_drawdown_circuit_breakers(self, gmig_state: Dict) -> Dict:
        """
        Get drawdown circuit breaker thresholds based on regime

        Different regimes tolerate different drawdowns:
        - Crisis: Very tight circuit breakers
        - Risk-on: Looser circuit breakers

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Circuit breaker parameters
        """
        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        # Alert-based overrides (most conservative)
        if alert_level == 'red':
            daily_limit = 0.02    # 2% daily loss triggers stop
            total_limit = 0.05    # 5% total drawdown triggers stop
            action = 'EMERGENCY_STOP'
        elif alert_level == 'orange':
            daily_limit = 0.05
            total_limit = 0.10
            action = 'REDUCE_ALL_50PCT'
        elif alert_level == 'yellow':
            daily_limit = 0.08
            total_limit = 0.15
            action = 'REDUCE_ALL_25PCT'
        else:
            # Regime-based thresholds
            regime_breakers = {
                'crisis': (0.02, 0.05, 'EMERGENCY_STOP'),
                'pre_recession': (0.05, 0.10, 'REDUCE_ALL_50PCT'),
                'risk_off': (0.08, 0.15, 'REDUCE_ALL_25PCT'),
                'tightening': (0.10, 0.20, 'REDUCE_SPECULATIVE'),
                'transitional': (0.10, 0.20, 'REVIEW_POSITIONS'),
                'easing': (0.12, 0.25, 'MONITOR_CLOSELY'),
                'risk_on': (0.15, 0.30, 'MONITOR_CLOSELY'),
            }
            daily_limit, total_limit, action = regime_breakers.get(
                regime,
                (0.10, 0.20, 'REVIEW_POSITIONS')
            )

        proposed = {
            'daily_drawdown_limit': daily_limit,
            'total_drawdown_limit': total_limit,
            'circuit_breaker_action': action,
            'regime': regime,
            'alert_level': alert_level,
            'enabled': True,
        }

        # SAFETY: Enforce heavy drawdown protection
        return self.safety.enforce_circuit_breakers(proposed, regime)

    def get_portfolio_heat_limits(self, gmig_state: Dict) -> Dict:
        """
        Get maximum portfolio heat (total risk) limits

        Args:
            gmig_state: Current GMIG strategic state

        Returns:
            Portfolio heat limit parameters
        """
        risk_adjustments = gmig_state.get('risk_adjustments', {})
        proposed_heat = risk_adjustments.get('max_portfolio_heat', 0.10)

        regime = gmig_state.get('macro_regime', 'unknown')
        alert_level = gmig_state.get('alert_level', 'green')
        if hasattr(alert_level, 'value'):
            alert_level = alert_level.value

        # SAFETY: Enforce conservative heat limits
        safe_heat = self.safety.enforce_portfolio_heat(proposed_heat, regime, alert_level)

        safe_heat['explanation'] = f"Maximum total portfolio risk at any time: {safe_heat['current_limit']:.1%}"
        safe_heat['calculation'] = 'Sum of (position_size * (1 - stop_loss_distance)) for all positions'

        return safe_heat
