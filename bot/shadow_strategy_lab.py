"""Production shadow laboratory for NIJA's strategy detectors.

The lab evaluates every registered detector against the same market snapshot,
tracks each candidate without submitting an order, and settles the candidate
after a configurable forward-bar horizon.  Outcomes are written to a dedicated
RegimePerformanceCalibrator instance so live-trade evidence and shadow evidence
never mix.

This module has no broker submission path and cannot place orders.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import pandas as pd

from bot.control.strategy_detectors import DetectorContext, build_default_detectors
from bot.control.trading_context import TradingContext
from bot.regime_performance_calibrator import RegimePerformanceCalibrator, normalize_regime

logger = logging.getLogger("nija.shadow_strategy_lab")


def _finite(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _bar_key(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


class ShadowStrategyLab:
    """Compare all detector strategies using forward market outcomes only."""

    def __init__(
        self,
        *,
        state_path: str = "data/shadow_strategy_lab_state.json",
        calibration_path: str = "data/shadow_strategy_performance.json",
        horizon_bars: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if enabled is None:
            enabled = os.getenv(
                "NIJA_SHADOW_STRATEGY_LAB_ENABLED", "true"
            ).strip().lower() in {"1", "true", "yes", "on"}
        self.enabled = bool(enabled)
        self.horizon_bars = max(
            1,
            int(
                horizon_bars
                if horizon_bars is not None
                else os.getenv("NIJA_SHADOW_STRATEGY_HORIZON_BARS", "5")
            ),
        )
        self.state_path = Path(state_path)
        self._lock = threading.RLock()
        self._detectors = list(build_default_detectors().values())
        self._pending: List[Dict[str, object]] = []
        self._seen: Deque[str] = deque(maxlen=2000)
        # Larger window than the live calibrator because eight strategy families
        # can be observed concurrently across several regimes.
        self.calibrator = RegimePerformanceCalibrator(
            state_path=calibration_path,
            window=max(
                400,
                int(os.getenv("NIJA_SHADOW_STRATEGY_WINDOW", "2000")),
            ),
        )
        self._load_state()
        logger.info(
            "ShadowStrategyLab initialized enabled=%s detectors=%d horizon=%d",
            self.enabled,
            len(self._detectors),
            self.horizon_bars,
        )

    @property
    def detector_names(self) -> List[str]:
        return [str(getattr(d, "strategy_name", "unknown")) for d in self._detectors]

    def observe(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        broker: str,
        market_regime: object,
        round_trip_cost_return: float = 0.0,
    ) -> List[Dict[str, object]]:
        """Settle matured shadow candidates and evaluate the newest closed bar.

        The returned rows are ranked observational recommendations only.  They
        are never submitted to a broker and do not alter the caller's decision.
        """
        if not self.enabled or df is None or df.empty:
            return []
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return []

        clean_broker = str(broker or "unknown").strip().lower() or "unknown"
        regime = normalize_regime(market_regime)
        cost = max(0.0, _finite(round_trip_cost_return))

        with self._lock:
            self._settle_matured(
                df,
                symbol=symbol,
                broker=clean_broker,
                round_trip_cost_return=cost,
            )

            current_bar = _bar_key(df.index[-1])
            context = DetectorContext(
                symbol=str(symbol),
                broker=clean_broker,
                market_regime=regime,
                trading_context=self._shadow_context(
                    symbol=str(symbol),
                    broker=clean_broker,
                    bar_key=current_bar,
                ),
            )

            signals = []
            for detector in self._detectors:
                try:
                    signal = detector.detect(df, context)
                except Exception as exc:
                    logger.debug(
                        "SHADOW_STRATEGY_DETECTOR_ERROR strategy=%s symbol=%s error=%s",
                        getattr(detector, "strategy_name", type(detector).__name__),
                        symbol,
                        exc,
                    )
                    continue
                if signal is not None:
                    signals.append(signal)

            direction_counts: Dict[str, int] = {}
            for signal in signals:
                direction = str(signal.direction or "unknown").lower()
                direction_counts[direction] = direction_counts.get(direction, 0) + 1

            rows: List[Dict[str, object]] = []
            entry_price = _finite(df["close"].iloc[-1])
            for signal in signals:
                strategy = str(signal.strategy or "unknown")
                direction = str(signal.direction or "unknown").lower()
                dedupe_key = "|".join(
                    [str(symbol), clean_broker, strategy, direction, current_bar]
                )
                if dedupe_key not in self._seen and entry_price > 0.0:
                    self._seen.append(dedupe_key)
                    self._pending.append(
                        {
                            "dedupe_key": dedupe_key,
                            "symbol": str(symbol),
                            "broker": clean_broker,
                            "strategy": strategy,
                            "direction": direction,
                            "regime": regime,
                            "entry_bar": current_bar,
                            "entry_price": entry_price,
                            "confidence": _finite(signal.confidence),
                        }
                    )

                detail = self.calibrator.score_strategy_candidate(
                    strategy=strategy,
                    regime=regime,
                    direction=direction,
                    base_score=max(
                        _finite(signal.raw_score),
                        _finite(signal.confidence),
                    ),
                    same_direction_confirmations=direction_counts.get(direction, 1),
                )
                # The lab is observational.  Use the calculated adaptive score
                # for recommendations even when live adaptive selection is off.
                rows.append(
                    {
                        **detail,
                        "shadow_only": True,
                        "entry_price": entry_price,
                        "supporting_evidence": list(signal.supporting_evidence),
                        "conflicting_evidence": list(signal.conflicting_evidence),
                    }
                )

            rows.sort(
                key=lambda row: (
                    float(row.get("adaptive_score", 0.0) or 0.0),
                    float(row.get("base_score", 0.0) or 0.0),
                ),
                reverse=True,
            )
            self._save_state()

        if rows:
            leader = rows[0]
            logger.info(
                "SHADOW_STRATEGY_RECOMMENDATION symbol=%s regime=%s strategy=%s "
                "direction=%s base=%.3f adaptive=%.3f samples=%d candidates=%d",
                symbol,
                regime,
                leader["strategy"],
                leader["direction"],
                float(leader["base_score"]),
                float(leader["adaptive_score"]),
                int(leader["sample_size"]),
                len(rows),
            )
        return rows

    def get_reports(self) -> List[Dict[str, object]]:
        return self.calibrator.report_all()

    def readiness(self) -> Dict[str, object]:
        """Return evidence coverage without enabling live strategy switching."""
        reports = self.get_reports()
        eligible = [
            row for row in reports
            if bool(row.get("eligible_for_review"))
        ]
        return {
            "enabled": self.enabled,
            "shadow_only": True,
            "detectors": self.detector_names,
            "pending_signals": len(self._pending),
            "observed_buckets": len(reports),
            "eligible_buckets": len(eligible),
            "minimum_samples": self.calibrator.selection_min_samples,
            "live_switching_enabled": False,
        }

    def _settle_matured(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        broker: str,
        round_trip_cost_return: float,
    ) -> None:
        index_map = {_bar_key(value): i for i, value in enumerate(df.index)}
        remaining: List[Dict[str, object]] = []

        for item in self._pending:
            if str(item.get("symbol")) != str(symbol) or str(item.get("broker")) != broker:
                remaining.append(item)
                continue

            entry_bar = str(item.get("entry_bar") or "")
            entry_pos = index_map.get(entry_bar)
            if entry_pos is None:
                # The source frame rolled past this signal before it could be
                # settled.  Drop it rather than inventing an exit price.
                logger.debug(
                    "SHADOW_STRATEGY_DROP_STALE symbol=%s strategy=%s entry_bar=%s",
                    symbol,
                    item.get("strategy"),
                    entry_bar,
                )
                continue

            exit_pos = entry_pos + self.horizon_bars
            if exit_pos >= len(df):
                remaining.append(item)
                continue

            entry_price = _finite(item.get("entry_price"))
            exit_price = _finite(df["close"].iloc[exit_pos])
            if entry_price <= 0.0 or exit_price <= 0.0:
                continue

            direction = str(item.get("direction") or "long").lower()
            if direction == "short":
                gross_return = (entry_price - exit_price) / entry_price
            else:
                gross_return = (exit_price - entry_price) / entry_price

            window = df.iloc[entry_pos + 1 : exit_pos + 1]
            if direction == "short":
                favorable = (
                    (entry_price - window["low"].astype(float)) / entry_price
                    if not window.empty else pd.Series(dtype=float)
                )
                adverse = (
                    (entry_price - window["high"].astype(float)) / entry_price
                    if not window.empty else pd.Series(dtype=float)
                )
            else:
                favorable = (
                    (window["high"].astype(float) - entry_price) / entry_price
                    if not window.empty else pd.Series(dtype=float)
                )
                adverse = (
                    (window["low"].astype(float) - entry_price) / entry_price
                    if not window.empty else pd.Series(dtype=float)
                )

            mfe = max(0.0, _finite(favorable.max() if not favorable.empty else 0.0))
            mae = min(0.0, _finite(adverse.min() if not adverse.empty else 0.0))
            net_return = gross_return - round_trip_cost_return

            self.calibrator.record_closed_trade(
                symbol=str(symbol),
                regime=item.get("regime") or "default",
                strategy=item.get("strategy") or "unknown",
                broker=broker,
                side=direction,
                net_return=net_return,
                gross_return=gross_return,
                execution_cost_return=round_trip_cost_return,
                mfe_return=mfe,
                mae_return=mae,
                exit_reason=f"shadow_forward_{self.horizon_bars}_bars",
                confidence=item.get("confidence"),
            )
            logger.info(
                "SHADOW_STRATEGY_SETTLED symbol=%s regime=%s strategy=%s "
                "direction=%s gross=%.5f cost=%.5f net=%.5f",
                symbol,
                item.get("regime"),
                item.get("strategy"),
                direction,
                gross_return,
                round_trip_cost_return,
                net_return,
            )

        self._pending = remaining

    @staticmethod
    def _shadow_context(*, symbol: str, broker: str, bar_key: str) -> TradingContext:
        token = f"{symbol}:{broker}:{bar_key}"
        return TradingContext(
            user_id="shadow_strategy_lab",
            trading_account_id=f"shadow:{broker}",
            broker=broker,
            broker_account_id="shadow",
            strategy_instance_id="shadow_strategy_lab",
            portfolio_id="shadow_strategy_lab",
            request_id=token,
            correlation_id=token,
            environment="production_shadow",
            mode="shadow",
        )

    def _load_state(self) -> None:
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            pending = payload.get("pending", [])
            seen = payload.get("seen", [])
            if isinstance(pending, list):
                self._pending = [
                    dict(item) for item in pending if isinstance(item, dict)
                ][-2000:]
            if isinstance(seen, list):
                for value in seen[-2000:]:
                    self._seen.append(str(value))
        except Exception as exc:
            logger.warning("ShadowStrategyLab state load skipped: %s", exc)

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "horizon_bars": self.horizon_bars,
                        "pending": self._pending[-2000:],
                        "seen": list(self._seen),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.state_path)
        except Exception as exc:
            logger.debug("ShadowStrategyLab state save skipped: %s", exc)


_SHADOW_LAB: Optional[ShadowStrategyLab] = None
_SHADOW_LAB_LOCK = threading.Lock()


def get_shadow_strategy_lab() -> ShadowStrategyLab:
    global _SHADOW_LAB
    if _SHADOW_LAB is None:
        with _SHADOW_LAB_LOCK:
            if _SHADOW_LAB is None:
                _SHADOW_LAB = ShadowStrategyLab()
    return _SHADOW_LAB
