"""
GMIG Safety Guardrails
======================

CRITICAL: Capital preservation > profit. Always.

This module implements conservative safety constraints to prevent over-optimization:
- Conservative thresholds
- Slow adaptation speeds
- Conservative leverage caps
- Heavy drawdown protection
"""

import logging
from typing import Dict
from datetime import datetime

logger = logging.getLogger("nija.gmig.safety")


# ============================================================================
# CONSERVATIVE SAFETY THRESHOLDS
# ============================================================================

SAFETY_THRESHOLDS = {
    # Leverage limits (VERY CONSERVATIVE)
    'max_leverage_ever': 2.0,           # Absolute hard cap - never exceed 2x
    'default_max_leverage': 1.5,        # Default max leverage
    'crisis_max_leverage': 1.0,         # No leverage in crisis

    # Position sizing (CONSERVATIVE)
    'max_single_position_pct': 0.10,   # Never more than 10% in single position
    'max_total_exposure_pct': 0.80,    # Never more than 80% deployed
    'max_correlated_exposure_pct': 0.25, # Max 25% in correlated assets

    # Drawdown protection (HEAVY)
    'daily_stop_loss_pct': 0.05,       # Stop everything at 5% daily loss
    'weekly_stop_loss_pct': 0.10,      # Stop everything at 10% weekly loss
    'max_drawdown_pct': 0.20,          # Maximum tolerated drawdown (20%)
    'circuit_breaker_pct': 0.15,       # Emergency stop at 15% drawdown

    # Portfolio heat (CONSERVATIVE)
    'max_portfolio_heat': 0.10,        # Total risk never above 10%
    'crisis_max_heat': 0.02,           # Crisis mode: 2% max
    'normal_max_heat': 0.10,           # Normal: 10% max

    # Adaptation speeds (SLOW)
    'regime_change_confirmation': 3,    # Require 3 consecutive readings
    'regime_change_cooldown_hours': 24, # Wait 24h between regime changes
    'position_size_change_max_pct': 0.20, # Max 20% position size change per day
    'leverage_change_max_per_day': 0.25,  # Max 0.25x leverage change per day
}


# ============================================================================
# CONSERVATIVE REGIME MAPPINGS
# ============================================================================

CONSERVATIVE_LEVERAGE_LIMITS = {
    'crisis': {'max': 1.0, 'recommended': 0.0},        # NO leverage in crisis
    'pre_recession': {'max': 1.0, 'recommended': 0.5},  # Minimal leverage
    'risk_off': {'max': 1.2, 'recommended': 1.0},
    'tightening': {'max': 1.5, 'recommended': 1.2},
    'transitional': {'max': 1.3, 'recommended': 1.0},
    'easing': {'max': 1.8, 'recommended': 1.5},
    'risk_on': {'max': 2.0, 'recommended': 1.5},        # Even risk-on capped at 2x
}

CONSERVATIVE_POSITION_CAPS = {
    'crisis': {'position': 0.02, 'total': 0.20},        # 2% per position, 20% total
    'pre_recession': {'position': 0.05, 'total': 0.40},  # 5% per position, 40% total
    'risk_off': {'position': 0.07, 'total': 0.60},
    'tightening': {'position': 0.08, 'total': 0.70},
    'transitional': {'position': 0.08, 'total': 0.65},
    'easing': {'position': 0.10, 'total': 0.80},
    'risk_on': {'position': 0.10, 'total': 0.80},        # Still conservative even in risk-on
}

CONSERVATIVE_CIRCUIT_BREAKERS = {
    'crisis': {'daily': 0.02, 'total': 0.05},           # Very tight in crisis
    'pre_recession': {'daily': 0.03, 'total': 0.08},
    'risk_off': {'daily': 0.05, 'total': 0.10},
    'tightening': {'daily': 0.05, 'total': 0.12},
    'transitional': {'daily': 0.05, 'total': 0.12},
    'easing': {'daily': 0.06, 'total': 0.15},
    'risk_on': {'daily': 0.05, 'total': 0.15},           # Still conservative
}


class SafetyGuardrails:
    """
    Enforces conservative safety guardrails on all GMIG outputs

    CAPITAL PRESERVATION > PROFIT

    All parameters passed through this class are constrained to conservative limits.
    This prevents over-optimization and protects capital.
    """

    def __init__(self):
        self.last_regime_change = None
        self.regime_confirmation_count = 0
        self.last_regime = "unknown"
        self.position_size_history = []
        self.leverage_history = []

        logger.info("🛡️ Safety Guardrails initialized - CAPITAL PRESERVATION MODE")
        logger.info(f"   Max Leverage Ever: {SAFETY_THRESHOLDS['max_leverage_ever']}x")
        logger.info(f"   Max Single Position: {SAFETY_THRESHOLDS['max_single_position_pct']:.0%}")
        logger.info(f"   Max Drawdown: {SAFETY_THRESHOLDS['max_drawdown_pct']:.0%}")

    def enforce_leverage_limits(self, proposed_leverage: Dict, regime: str) -> Dict:
        """
        Enforce conservative leverage limits

        Args:
            proposed_leverage: Proposed leverage parameters
            regime: Current macro regime

        Returns:
            Safe leverage parameters (capped at conservative limits)
        """
        # Get conservative limits for regime
        regime_limits = CONSERVATIVE_LEVERAGE_LIMITS.get(regime, {'max': 1.5, 'recommended': 1.0})

        # Apply absolute hard cap
        safe_max = min(
            proposed_leverage.get('max_leverage', 2.0),
            regime_limits['max'],
            SAFETY_THRESHOLDS['max_leverage_ever']  # NEVER exceed this
        )

        safe_recommended = min(
            proposed_leverage.get('recommended_leverage', 1.5),
            regime_limits['recommended'],
            safe_max
        )

        # Slow adaptation - max change per day
        if self.leverage_history:
            last_leverage = self.leverage_history[-1]
            max_change = SAFETY_THRESHOLDS['leverage_change_max_per_day']

            if abs(safe_recommended - last_leverage) > max_change:
                # Gradually move toward target
                if safe_recommended > last_leverage:
                    safe_recommended = last_leverage + max_change
                else:
                    safe_recommended = last_leverage - max_change

        self.leverage_history.append(safe_recommended)

        # Log if we capped it
        if safe_max < proposed_leverage.get('max_leverage', 0):
            logger.warning(f"⚠️ Leverage capped: {proposed_leverage.get('max_leverage'):.2f}x → {safe_max:.2f}x (SAFETY)")

        return {
            'max_leverage': safe_max,
            'recommended_leverage': safe_recommended,
            'safety_capped': safe_max < proposed_leverage.get('max_leverage', 999),
            'regime': regime,
        }

    def enforce_position_caps(self,
                             proposed_caps: Dict,
                             regime: str,
                             account_balance: float) -> Dict:
        """
        Enforce conservative position size caps

        Args:
            proposed_caps: Proposed position caps
            regime: Current macro regime
            account_balance: Account balance

        Returns:
            Safe position caps (capped at conservative limits)
        """
        # Get conservative limits for regime
        regime_caps = CONSERVATIVE_POSITION_CAPS.get(regime, {'position': 0.08, 'total': 0.65})

        # Apply conservative caps
        safe_position_pct = min(
            proposed_caps.get('max_position_pct', 0.20),
            regime_caps['position'],
            SAFETY_THRESHOLDS['max_single_position_pct']  # NEVER exceed
        )

        safe_total_pct = min(
            proposed_caps.get('max_total_exposure_pct', 1.0),
            regime_caps['total'],
            SAFETY_THRESHOLDS['max_total_exposure_pct']  # NEVER exceed
        )

        return {
            'max_position_size_usd': account_balance * safe_position_pct,
            'max_position_pct': safe_position_pct,
            'max_total_exposure_usd': account_balance * safe_total_pct,
            'max_total_exposure_pct': safe_total_pct,
            'max_correlated_exposure_pct': SAFETY_THRESHOLDS['max_correlated_exposure_pct'],
            'safety_enforced': True,
            'regime': regime,
        }

    def enforce_circuit_breakers(self,
                                proposed_breakers: Dict,
                                regime: str) -> Dict:
        """
        Enforce heavy drawdown protection

        Args:
            proposed_breakers: Proposed circuit breaker thresholds
            regime: Current macro regime

        Returns:
            Safe circuit breakers (more conservative)
        """
        # Get conservative limits for regime
        regime_breakers = CONSERVATIVE_CIRCUIT_BREAKERS.get(regime, {'daily': 0.05, 'total': 0.12})

        # Always use MOST conservative of proposed vs regime vs absolute limits
        safe_daily = min(
            proposed_breakers.get('daily_drawdown_limit', 0.10),
            regime_breakers['daily'],
            SAFETY_THRESHOLDS['daily_stop_loss_pct']
        )

        safe_total = min(
            proposed_breakers.get('total_drawdown_limit', 0.20),
            regime_breakers['total'],
            SAFETY_THRESHOLDS['circuit_breaker_pct']
        )

        # Determine action (always conservative)
        if safe_daily <= 0.02 or safe_total <= 0.05:
            action = 'EMERGENCY_STOP'
        elif safe_daily <= 0.03 or safe_total <= 0.08:
            action = 'REDUCE_ALL_75PCT'
        elif safe_daily <= 0.05 or safe_total <= 0.10:
            action = 'REDUCE_ALL_50PCT'
        else:
            action = 'REDUCE_ALL_25PCT'

        return {
            'daily_drawdown_limit': safe_daily,
            'weekly_drawdown_limit': SAFETY_THRESHOLDS['weekly_stop_loss_pct'],
            'total_drawdown_limit': safe_total,
            'max_drawdown_ever': SAFETY_THRESHOLDS['max_drawdown_pct'],
            'circuit_breaker_action': action,
            'enabled': True,
            'safety_enforced': True,
        }

    def enforce_portfolio_heat(self,
                              proposed_heat: float,
                              regime: str,
                              alert_level: str) -> Dict:
        """
        Enforce conservative portfolio heat limits

        Args:
            proposed_heat: Proposed max portfolio heat
            regime: Current macro regime
            alert_level: Current alert level

        Returns:
            Safe heat limit
        """
        # Crisis override
        if alert_level in ['red', 'orange'] or regime == 'crisis':
            safe_heat = SAFETY_THRESHOLDS['crisis_max_heat']
        else:
            safe_heat = min(
                proposed_heat,
                SAFETY_THRESHOLDS['normal_max_heat']
            )

        return {
            'max_portfolio_heat': safe_heat,
            'crisis_max_heat': SAFETY_THRESHOLDS['crisis_max_heat'],
            'normal_max_heat': SAFETY_THRESHOLDS['normal_max_heat'],
            'current_limit': safe_heat,
            'safety_enforced': True,
        }

    def confirm_regime_change(self, new_regime: str) -> bool:
        """
        Require confirmation before accepting regime change (slow adaptation)

        Args:
            new_regime: Proposed new regime

        Returns:
            True if regime change is confirmed
        """
        # First reading of new regime
        if new_regime != self.last_regime:
            self.regime_confirmation_count = 1
            self.last_regime = new_regime
            logger.info(f"Regime change proposed: → {new_regime} (1/{SAFETY_THRESHOLDS['regime_change_confirmation']})")
            return False

        # Increment confirmation count
        self.regime_confirmation_count += 1

        # Check if we have enough confirmations
        if self.regime_confirmation_count >= SAFETY_THRESHOLDS['regime_change_confirmation']:
            # Check cooldown period
            if self.last_regime_change:
                hours_since = (datetime.now() - self.last_regime_change).total_seconds() / 3600
                if hours_since < SAFETY_THRESHOLDS['regime_change_cooldown_hours']:
                    logger.warning(f"⚠️ Regime change blocked by cooldown ({hours_since:.1f}h < {SAFETY_THRESHOLDS['regime_change_cooldown_hours']}h)")
                    return False

            # Confirmed!
            self.last_regime_change = datetime.now()
            logger.info(f"✓ Regime change CONFIRMED: → {new_regime}")
            return True
        else:
            logger.info(f"Regime change proposed: → {new_regime} ({self.regime_confirmation_count}/{SAFETY_THRESHOLDS['regime_change_confirmation']})")
            return False

    def get_safety_summary(self) -> Dict:
        """Get safety guardrails summary"""
        return {
            'mode': 'CAPITAL PRESERVATION',
            'priority': 'Safety > Profit',
            'thresholds': SAFETY_THRESHOLDS,
            'max_leverage_ever': SAFETY_THRESHOLDS['max_leverage_ever'],
            'max_position_size': SAFETY_THRESHOLDS['max_single_position_pct'],
            'max_drawdown': SAFETY_THRESHOLDS['max_drawdown_pct'],
            'regime_confirmation_required': SAFETY_THRESHOLDS['regime_change_confirmation'],
        }


# Singleton instance
_safety_instance = None

def get_safety_guardrails() -> SafetyGuardrails:
    """Get singleton safety guardrails instance"""
    global _safety_instance
    if _safety_instance is None:
        _safety_instance = SafetyGuardrails()
    return _safety_instance
