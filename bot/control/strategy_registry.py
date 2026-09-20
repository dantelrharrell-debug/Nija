from __future__ import annotations

from typing import Dict, List

import pandas as pd

from bot.feature_flags import FeatureFlag, get_feature_flags
from bot.control.strategy_detectors import BaseDetector, DetectorContext, build_default_detectors
from bot.control.strategy_signal import StrategySignal
from bot.control.trading_context import TradingContext


class StrategyDetectorRegistry:
    """
    Executes configured strategy detectors and returns candidate signals.
    """

    def __init__(self, detectors: Dict[FeatureFlag, BaseDetector] | None = None) -> None:
        self.detectors = detectors or build_default_detectors()

    def detect(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        broker: str,
        market_regime: str,
        trading_context: TradingContext,
    ) -> List[StrategySignal]:
        if broker.strip().lower() != trading_context.broker:
            raise ValueError("broker_mismatch_with_trading_context")
        context = DetectorContext(
            symbol=symbol,
            broker=broker,
            trading_context=trading_context,
            market_regime=market_regime,
        )
        out: List[StrategySignal] = []
        for flag_name, detector in self.detectors.items():
            if not self._flag_enabled(flag_name):
                continue
            signal = detector.detect(df, context)
            if signal is not None:
                out.append(signal)
        return out

    @staticmethod
    def _flag_enabled(name: FeatureFlag) -> bool:
        return get_feature_flags().is_enabled(name)
