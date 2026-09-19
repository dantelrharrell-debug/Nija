from __future__ import annotations

import os
from typing import Dict, List

import pandas as pd

from bot.control.strategy_detectors import BaseDetector, DetectorContext, build_default_detectors
from bot.control.strategy_signal import StrategySignal


class StrategyDetectorRegistry:
    """
    Executes configured strategy detectors and returns candidate signals.
    """

    def __init__(self, detectors: Dict[str, BaseDetector] | None = None) -> None:
        self.detectors = detectors or build_default_detectors()

    def detect(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        broker: str,
        market_regime: str,
    ) -> List[StrategySignal]:
        context = DetectorContext(symbol=symbol, broker=broker, market_regime=market_regime)
        out: List[StrategySignal] = []
        for flag_name, detector in self.detectors.items():
            if not self._flag_enabled(flag_name):
                continue
            signal = detector.detect(df, context)
            if signal is not None:
                out.append(signal)
        return out

    @staticmethod
    def _flag_enabled(name: str) -> bool:
        return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")
