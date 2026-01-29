"""
Macro Regime Forecaster
=======================

Forecasts macro economic regimes based on cross-market analysis:
- Risk On/Off detection
- Inflation/Deflation cycles
- Growth/Recession indicators
- Central bank policy shifts
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
import logging

from .mmin_config import MACRO_REGIME_CONFIG

logger = logging.getLogger("nija.mmin.macro")


class MacroRegime(Enum):
    """Macro economic regimes"""
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    INFLATION = "inflation"
    DEFLATION = "deflation"
    GROWTH = "growth"
    RECESSION = "recession"
    TRANSITIONAL = "transitional"
    UNKNOWN = "unknown"


class MacroRegimeForecaster:
    """
    Forecasts macro economic regime based on cross-market signals

    Regime Detection Logic:
    - RISK_ON: Crypto ↑, Equities ↑, Bonds ↓, VIX ↓
    - RISK_OFF: Crypto ↓, Equities ↓, Bonds ↑, VIX ↑
    - INFLATION: Commodities ↑, Bonds ↓, Dollar ↓
    - DEFLATION: Commodities ↓, Bonds ↑, Dollar ↑
    - GROWTH: Equities ↑, Crypto ↑, moderate inflation
    - RECESSION: Everything ↓ except bonds/USD
    """

    def __init__(self, config: Dict = None):
        """
        Initialize macro regime forecaster

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or MACRO_REGIME_CONFIG
        self.detection_window = self.config['detection_window']
        self.min_regime_duration = self.config['min_regime_duration']

        # Current regime state
        self.current_regime: MacroRegime = MacroRegime.UNKNOWN
        self.regime_confidence: float = 0.0
        self.regime_duration: int = 0
        self.regime_history: List[Tuple[datetime, MacroRegime, float]] = []

        # Regime indicators
        self.regime_indicators = self.config.get('indicators', {})

        logger.info("MacroRegimeForecaster initialized")

    def forecast_regime(self, market_data: Dict[str, pd.DataFrame]) -> Dict:
        """
        Forecast current macro regime from multi-market data

        Args:
            market_data: Dictionary mapping market types to DataFrames

        Returns:
            Dictionary with regime forecast and supporting data
        """
        # Calculate regime signals
        signals = self._calculate_regime_signals(market_data)

        # Score each regime
        regime_scores = self._score_regimes(signals)

        # Select regime with highest score
        best_regime = max(regime_scores.items(), key=lambda x: x[1])
        regime, confidence = best_regime

        # Update regime state (with hysteresis to avoid flip-flopping)
        previous_regime = self.current_regime
        if regime != self.current_regime:
            if confidence >= 0.6 and self.regime_duration >= self.min_regime_duration:
                logger.info(f"Regime change: {self.current_regime.value} → {regime.value} (confidence={confidence:.2f})")
                self.current_regime = regime
                self.regime_duration = 0
                self.regime_history.append((datetime.now(), regime, confidence))
            else:
                # Not enough confidence or duration to change regime
                self.regime_duration += 1
        else:
            self.regime_duration += 1

        self.regime_confidence = confidence

        return {
            'regime': self.current_regime,
            'confidence': self.regime_confidence,
            'duration': self.regime_duration,
            'previous_regime': previous_regime,
            'regime_scores': {r.value: s for r, s in regime_scores.items()},
            'signals': signals,
            'trading_implications': self._get_trading_implications(self.current_regime),
        }

    def _calculate_regime_signals(self, market_data: Dict[str, pd.DataFrame]) -> Dict:
        """Calculate signals for regime detection"""
        signals = {}

        # Crypto momentum
        if 'crypto' in market_data and market_data['crypto']:
            crypto_df = list(market_data['crypto'].values())[0] if market_data['crypto'] else None
            if crypto_df is not None and len(crypto_df) >= self.detection_window:
                crypto_returns = crypto_df['close'].pct_change(self.detection_window).iloc[-1]
                signals['crypto_momentum'] = crypto_returns
                signals['crypto_volatility'] = crypto_df['close'].pct_change().std()

        # Equity momentum
        if 'equities' in market_data and market_data['equities']:
            equity_df = list(market_data['equities'].values())[0] if market_data['equities'] else None
            if equity_df is not None and len(equity_df) >= self.detection_window:
                equity_returns = equity_df['close'].pct_change(self.detection_window).iloc[-1]
                signals['equity_momentum'] = equity_returns
                signals['equity_volatility'] = equity_df['close'].pct_change().std()

        # Bond momentum (inverse relationship with risk)
        if 'bonds' in market_data and market_data['bonds']:
            bond_df = list(market_data['bonds'].values())[0] if market_data['bonds'] else None
            if bond_df is not None and len(bond_df) >= self.detection_window:
                bond_returns = bond_df['close'].pct_change(self.detection_window).iloc[-1]
                signals['bond_momentum'] = bond_returns

        # Commodity momentum (inflation proxy)
        if 'commodities' in market_data and market_data['commodities']:
            commodity_df = list(market_data['commodities'].values())[0] if market_data['commodities'] else None
            if commodity_df is not None and len(commodity_df) >= self.detection_window:
                commodity_returns = commodity_df['close'].pct_change(self.detection_window).iloc[-1]
                signals['commodity_momentum'] = commodity_returns

        return signals

    def _score_regimes(self, signals: Dict) -> Dict[MacroRegime, float]:
        """Score each regime based on signals"""
        scores = {}

        # RISK_ON: Crypto ↑, Equities ↑, Bonds ↓
        risk_on_score = 0.0
        if 'crypto_momentum' in signals and signals['crypto_momentum'] > 0:
            risk_on_score += 0.4
        if 'equity_momentum' in signals and signals['equity_momentum'] > 0:
            risk_on_score += 0.4
        if 'bond_momentum' in signals and signals['bond_momentum'] < 0:
            risk_on_score += 0.2
        scores[MacroRegime.RISK_ON] = risk_on_score

        # RISK_OFF: Crypto ↓, Equities ↓, Bonds ↑
        risk_off_score = 0.0
        if 'crypto_momentum' in signals and signals['crypto_momentum'] < 0:
            risk_off_score += 0.4
        if 'equity_momentum' in signals and signals['equity_momentum'] < 0:
            risk_off_score += 0.4
        if 'bond_momentum' in signals and signals['bond_momentum'] > 0:
            risk_off_score += 0.2
        scores[MacroRegime.RISK_OFF] = risk_off_score

        # INFLATION: Commodities ↑, Bonds ↓
        inflation_score = 0.0
        if 'commodity_momentum' in signals and signals['commodity_momentum'] > 0:
            inflation_score += 0.6
        if 'bond_momentum' in signals and signals['bond_momentum'] < 0:
            inflation_score += 0.4
        scores[MacroRegime.INFLATION] = inflation_score

        # DEFLATION: Commodities ↓, Bonds ↑
        deflation_score = 0.0
        if 'commodity_momentum' in signals and signals['commodity_momentum'] < 0:
            deflation_score += 0.6
        if 'bond_momentum' in signals and signals['bond_momentum'] > 0:
            deflation_score += 0.4
        scores[MacroRegime.DEFLATION] = deflation_score

        # GROWTH: Equities ↑, Crypto ↑
        growth_score = 0.0
        if 'equity_momentum' in signals and signals['equity_momentum'] > 0.05:
            growth_score += 0.5
        if 'crypto_momentum' in signals and signals['crypto_momentum'] > 0.05:
            growth_score += 0.5
        scores[MacroRegime.GROWTH] = growth_score

        # RECESSION: Equities ↓, Crypto ↓, Commodities ↓
        recession_score = 0.0
        if 'equity_momentum' in signals and signals['equity_momentum'] < -0.05:
            recession_score += 0.4
        if 'crypto_momentum' in signals and signals['crypto_momentum'] < -0.05:
            recession_score += 0.3
        if 'commodity_momentum' in signals and signals['commodity_momentum'] < -0.05:
            recession_score += 0.3
        scores[MacroRegime.RECESSION] = recession_score

        # TRANSITIONAL: Mixed signals
        max_score = max(scores.values()) if scores else 0.0
        if max_score < 0.5:
            scores[MacroRegime.TRANSITIONAL] = 0.6
        else:
            scores[MacroRegime.TRANSITIONAL] = 0.0

        return scores

    def _get_trading_implications(self, regime: MacroRegime) -> Dict:
        """Get trading implications for a regime"""
        implications = {
            MacroRegime.RISK_ON: {
                'preferred_markets': ['crypto', 'equities'],
                'avoid_markets': ['bonds'],
                'position_sizing': 'aggressive',
                'strategy_focus': 'momentum',
                'leverage': 'increase',
            },
            MacroRegime.RISK_OFF: {
                'preferred_markets': ['bonds', 'forex'],
                'avoid_markets': ['crypto'],
                'position_sizing': 'conservative',
                'strategy_focus': 'defensive',
                'leverage': 'reduce',
            },
            MacroRegime.INFLATION: {
                'preferred_markets': ['commodities', 'crypto'],
                'avoid_markets': ['bonds'],
                'position_sizing': 'balanced',
                'strategy_focus': 'inflation_hedge',
                'leverage': 'moderate',
            },
            MacroRegime.DEFLATION: {
                'preferred_markets': ['bonds', 'forex'],
                'avoid_markets': ['commodities'],
                'position_sizing': 'conservative',
                'strategy_focus': 'preservation',
                'leverage': 'minimal',
            },
            MacroRegime.GROWTH: {
                'preferred_markets': ['equities', 'crypto'],
                'avoid_markets': [],
                'position_sizing': 'aggressive',
                'strategy_focus': 'growth',
                'leverage': 'increase',
            },
            MacroRegime.RECESSION: {
                'preferred_markets': ['bonds'],
                'avoid_markets': ['crypto', 'equities', 'commodities'],
                'position_sizing': 'minimal',
                'strategy_focus': 'cash_preservation',
                'leverage': 'none',
            },
            MacroRegime.TRANSITIONAL: {
                'preferred_markets': ['forex'],
                'avoid_markets': [],
                'position_sizing': 'balanced',
                'strategy_focus': 'range_trading',
                'leverage': 'moderate',
            },
            MacroRegime.UNKNOWN: {
                'preferred_markets': [],
                'avoid_markets': [],
                'position_sizing': 'conservative',
                'strategy_focus': 'observation',
                'leverage': 'minimal',
            },
        }

        return implications.get(regime, implications[MacroRegime.UNKNOWN])

    def get_regime_transitions(self, lookback: int = 10) -> List[Dict]:
        """Get recent regime transitions"""
        recent = self.regime_history[-lookback:] if self.regime_history else []

        transitions = []
        for i in range(1, len(recent)):
            prev_time, prev_regime, prev_conf = recent[i-1]
            curr_time, curr_regime, curr_conf = recent[i]

            if prev_regime != curr_regime:
                transitions.append({
                    'timestamp': curr_time,
                    'from_regime': prev_regime.value,
                    'to_regime': curr_regime.value,
                    'confidence': curr_conf,
                    'duration_days': (curr_time - prev_time).days,
                })

        return transitions
