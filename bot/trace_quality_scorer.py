"""Trace-path quality scoring for Execution Intelligence Layer v2."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("nija.trace_quality_scorer")


@dataclass
class TraceQualityScore:
    """Predicted quality metadata for a trace attempt."""

    trace_id: str
    pass_probability: Optional[float]
    expected_grade: str
    slippage_risk_score: float
    regime_alignment_score: float
    path_seen_before: bool
    similar_path_win_rate: float
    confidence_interval: float


class TraceQualityScorer:
    """Learns trace-path quality and predicts pre-fill trade quality."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._samples: Deque[Dict[str, Any]] = deque(maxlen=5000)
        self._path_stats: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"wins": 0.0, "total": 0.0, "slippage_sum": 0.0, "regime_match": 0.0}
        )
        self._score_by_trace_id: Dict[str, TraceQualityScore] = {}
        self._trained_at: float = 0.0
        self._model: Optional[Any] = None
        self._model_meta: Dict[str, Any] = {}
        self._last_retrain_attempt: float = 0.0
        self._retrain_interval_sec: float = max(
            3600.0,
            float(os.getenv("NIJA_EIL_SCORER_RETRAIN_INTERVAL_H", "6") or "6") * 3600.0,
        )
        self._redis_key = "nija:eil:scorer_weights"
        self._bootstrap_from_redis()

    @staticmethod
    def _regime_value(trace: Dict[str, Any]) -> str:
        regime = trace.get("regime")
        if regime is None:
            return "unknown"
        if hasattr(regime, "value"):
            return str(regime.value).lower()
        return str(regime).lower()

    @staticmethod
    def _extract_trace_path(trace: Dict[str, Any]) -> List[str]:
        events = trace.get("events") or []
        path: List[str] = []
        for event in events:
            stage = str((event or {}).get("stage") or "unknown")
            outcome = str((event or {}).get("outcome") or "unknown")
            path.append(f"{stage}:{outcome}")
        return path

    @staticmethod
    def _path_hash(path: Sequence[str]) -> str:
        if not path:
            return "empty_path"
        return "|".join(path)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_feature_row(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        path = self._extract_trace_path(trace)
        path_hash = self._path_hash(path)
        events = trace.get("events") or []
        extra_union: Dict[str, Any] = {}
        for event in events:
            extra_union.update((event or {}).get("extra") or {})

        confidence = self._safe_float(trace.get("confidence") or extra_union.get("confidence"))
        adx = self._safe_float(trace.get("adx") or extra_union.get("adx"))
        gate_score = self._safe_float(trace.get("gate_score") or extra_union.get("gate_score"))
        gate_min = self._safe_float(extra_union.get("gate_min"), 1.0)
        gate_margin = gate_score - gate_min

        slippage_bps = self._safe_float(trace.get("slippage_bps") or extra_union.get("slippage_bps"))
        fill_latency_ms = self._safe_float(trace.get("fill_latency_ms") or extra_union.get("fill_latency_ms"))

        regime = self._regime_value(trace)
        regime_alignment = 1.0 if ("trend" in regime and "ai_gate:pass" in path_hash) else 0.5

        return {
            "trace_id": str(trace.get("trace_id") or ""),
            "path": path,
            "path_hash": path_hash,
            "regime": regime,
            "confidence": confidence,
            "adx": adx,
            "gate_score": gate_score,
            "gate_margin": gate_margin,
            "slippage_bps": slippage_bps,
            "fill_latency_ms": fill_latency_ms,
            "regime_alignment": regime_alignment,
            "status": str(trace.get("status") or "in_progress"),
            "quality_grade": str(trace.get("quality_grade") or ""),
            "pnl_pct": self._safe_float(trace.get("pnl_pct"), 0.0),
        }

    def _grade_to_pass_target(self, grade: str, pnl_pct: float) -> Optional[int]:
        g = (grade or "").upper().strip()
        if g in {"A", "B"}:
            return 1
        if g in {"C", "D"}:
            return 0
        if pnl_pct != 0.0:
            return 1 if pnl_pct > 0 else 0
        return None

    def _maybe_retrain_model_locked(self) -> None:
        now = time.time()
        if now - self._last_retrain_attempt < self._retrain_interval_sec:
            return
        self._last_retrain_attempt = now

        if len(self._samples) < 50:
            return

        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.linear_model import LogisticRegression
        except Exception:
            return

        rows = list(self._samples)[-500:]
        x: List[List[float]] = []
        y: List[int] = []
        for row in rows:
            label = self._grade_to_pass_target(row.get("quality_grade", ""), self._safe_float(row.get("pnl_pct")))
            if label is None:
                continue
            x.append(
                [
                    self._safe_float(row.get("confidence")),
                    self._safe_float(row.get("adx")),
                    self._safe_float(row.get("gate_score")),
                    self._safe_float(row.get("gate_margin")),
                    self._safe_float(row.get("slippage_bps")),
                    self._safe_float(row.get("fill_latency_ms")),
                    self._safe_float(row.get("regime_alignment"), 0.5),
                ]
            )
            y.append(label)

        if len(y) < 50 or len(set(y)) < 2:
            return

        model: Any
        if len(y) >= 1000:
            model = GradientBoostingClassifier(random_state=42)
            model_name = "gradient_boosting"
        else:
            model = LogisticRegression(max_iter=250)
            model_name = "logistic_regression"

        model.fit(x, y)
        self._model = model
        self._model_meta = {
            "model": model_name,
            "trained_at": now,
            "sample_count": len(y),
        }
        self._trained_at = now
        self._persist_model_meta_to_redis_locked()

    def _persist_model_meta_to_redis_locked(self) -> None:
        payload = json.dumps(self._model_meta)
        try:
            try:
                from bot.redis_runtime import create_redis
            except ImportError:
                from redis_runtime import create_redis  # type: ignore[import]
            client = create_redis(decode_responses=True)
            client.set(self._redis_key, payload)
        except Exception:
            pass

    def _bootstrap_from_redis(self) -> None:
        try:
            try:
                from bot.redis_runtime import create_redis
            except ImportError:
                from redis_runtime import create_redis  # type: ignore[import]
            client = create_redis(decode_responses=True)
            raw = client.get(self._redis_key)
            if not raw:
                return
            meta = json.loads(raw)
            if isinstance(meta, dict):
                self._model_meta = dict(meta)
                self._trained_at = self._safe_float(meta.get("trained_at"), 0.0)
        except Exception:
            return

    def record_terminal_outcome(
        self,
        trace: Dict[str, Any],
        *,
        quality_grade: str = "",
        pnl_pct: float = 0.0,
        slippage_bps: Optional[float] = None,
    ) -> None:
        """Add a terminal trace sample for model learning."""
        with self._lock:
            row = self._build_feature_row(trace)
            if quality_grade:
                row["quality_grade"] = quality_grade
            if pnl_pct:
                row["pnl_pct"] = pnl_pct
            if slippage_bps is not None:
                row["slippage_bps"] = float(slippage_bps)

            self._samples.append(row)
            stats = self._path_stats[row["path_hash"]]
            stats["total"] += 1.0
            label = self._grade_to_pass_target(str(row.get("quality_grade") or ""), self._safe_float(row.get("pnl_pct")))
            if label == 1:
                stats["wins"] += 1.0
            stats["slippage_sum"] += abs(self._safe_float(row.get("slippage_bps")))
            stats["regime_match"] += self._safe_float(row.get("regime_alignment"), 0.5)
            self._maybe_retrain_model_locked()

    def score_trace(self, trace: Dict[str, Any]) -> TraceQualityScore:
        """Score an in-progress trace using historical path and optional ML model."""
        with self._lock:
            row = self._build_feature_row(trace)
            path_hash = row["path_hash"]
            stats = self._path_stats.get(path_hash)
            seen_before = bool(stats and stats.get("total", 0.0) > 0)
            total = self._safe_float((stats or {}).get("total"), 0.0)
            wins = self._safe_float((stats or {}).get("wins"), 0.0)
            similar_win_rate = (wins + 1.0) / (total + 2.0)

            pass_probability: Optional[float]
            if total < 5:
                pass_probability = None
            else:
                pass_probability = similar_win_rate

            if self._model is not None and len(self._samples) >= 50:
                feature = [
                    [
                        self._safe_float(row.get("confidence")),
                        self._safe_float(row.get("adx")),
                        self._safe_float(row.get("gate_score")),
                        self._safe_float(row.get("gate_margin")),
                        self._safe_float(row.get("slippage_bps")),
                        self._safe_float(row.get("fill_latency_ms")),
                        self._safe_float(row.get("regime_alignment"), 0.5),
                    ]
                ]
                try:
                    if hasattr(self._model, "predict_proba"):
                        pass_probability = float(self._model.predict_proba(feature)[0][1])
                except Exception:
                    pass

            if pass_probability is None:
                expected_grade = "B"
            elif pass_probability >= 0.75:
                expected_grade = "A"
            elif pass_probability >= 0.55:
                expected_grade = "B"
            elif pass_probability >= 0.35:
                expected_grade = "C"
            else:
                expected_grade = "D"

            avg_slippage = self._safe_float((stats or {}).get("slippage_sum"), 0.0) / max(total, 1.0)
            slippage_risk = min(1.0, avg_slippage / 50.0)
            regime_alignment = self._safe_float(row.get("regime_alignment"), 0.5)
            confidence_interval = min(1.0, 1.0 / math.sqrt(max(total, 1.0)))

            score = TraceQualityScore(
                trace_id=str(trace.get("trace_id") or row["trace_id"]),
                pass_probability=pass_probability,
                expected_grade=expected_grade,
                slippage_risk_score=slippage_risk,
                regime_alignment_score=regime_alignment,
                path_seen_before=seen_before,
                similar_path_win_rate=similar_win_rate,
                confidence_interval=confidence_interval,
            )
            self._score_by_trace_id[score.trace_id] = score
            return score

    def get_trace_score(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Return cached score payload for a trace id."""
        with self._lock:
            score = self._score_by_trace_id.get(str(trace_id))
            if score is None:
                return None
            return asdict(score)

    def get_model_status(self) -> Dict[str, Any]:
        """Return current model metadata and training state."""
        with self._lock:
            return {
                "trained": self._model is not None,
                "trained_at": datetime.utcfromtimestamp(self._trained_at).isoformat() if self._trained_at else None,
                "samples": len(self._samples),
                "model_meta": dict(self._model_meta),
            }


_scorer_singleton: Optional[TraceQualityScorer] = None
_scorer_lock = threading.Lock()


def get_trace_quality_scorer() -> TraceQualityScorer:
    """Return process singleton TraceQualityScorer."""
    global _scorer_singleton
    if _scorer_singleton is None:
        with _scorer_lock:
            if _scorer_singleton is None:
                _scorer_singleton = TraceQualityScorer()
    return _scorer_singleton
