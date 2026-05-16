"""Real-time failure clustering for Execution Intelligence Layer v2."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("nija.failure_cluster_engine")


@dataclass
class FailureClusterRecord:
    """Aggregated rejection-cluster record."""

    cluster_id: str
    trace_path: List[str]
    regime: str
    sample_count: int
    first_seen: str
    last_seen: str
    rejection_rate: float
    centroid_confidence: float
    centroid_adx: float
    label: str


class FailureClusterEngine:
    """Clusters terminal rejection traces by trace-path hash and regime."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rolling_window_sec = 4 * 60 * 60
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=10000)
        self._clusters: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(dict)
        self._regime_feedback_bumped_at: Dict[str, float] = {}

    @staticmethod
    def _norm_regime(value: Any) -> str:
        if value is None:
            return "unknown"
        if hasattr(value, "value"):
            return str(value.value).lower()
        return str(value).lower()

    @staticmethod
    def _trace_path(trace: Dict[str, Any]) -> List[str]:
        if isinstance(trace.get("trace_path"), list):
            return [str(p) for p in (trace.get("trace_path") or [])]
        events = trace.get("events") or []
        return [f"{(e or {}).get('stage', 'unknown')}:{(e or {}).get('outcome', 'unknown')}" for e in events]

    @staticmethod
    def _path_hash(path: Sequence[str]) -> str:
        joined = "|".join(path) if path else "empty"
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _is_nontrivial_rejection(trace: Dict[str, Any]) -> bool:
        status = str(trace.get("status") or "").lower()
        if status != "rejected":
            return False
        reason = str(trace.get("terminal_reason") or "").lower()
        if not reason:
            return True
        trivial_tokens = ("no_signal", "scan_complete_no_signal", "none")
        return not any(token in reason for token in trivial_tokens)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def ingest_terminal_trace(self, trace: Dict[str, Any]) -> None:
        """Update rolling failure clusters from terminal traces."""
        if not self._is_nontrivial_rejection(trace):
            return

        now = time.time()
        path = self._trace_path(trace)
        regime = self._norm_regime(trace.get("regime"))
        path_hash = self._path_hash(path)
        confidence = self._safe_float(trace.get("confidence"))
        adx = self._safe_float(trace.get("adx"))

        with self._lock:
            self._entries.append(
                {
                    "ts": now,
                    "path": path,
                    "path_hash": path_hash,
                    "regime": regime,
                    "confidence": confidence,
                    "adx": adx,
                    "trace_id": str(trace.get("trace_id") or ""),
                }
            )
            self._prune_locked(now)
            self._rebuild_clusters_locked(now)
            clusters = self._clusters

        self._persist_clusters_to_postgres(clusters)
        self._emit_feedback_if_needed()

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self._rolling_window_sec
        while self._entries and self._entries[0].get("ts", 0.0) < cutoff:
            self._entries.popleft()

    def _rebuild_clusters_locked(self, now: float) -> None:
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for entry in self._entries:
            grouped[(entry["path_hash"], entry["regime"])].append(entry)

        new_clusters: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for (path_hash, regime), rows in grouped.items():
            if not rows:
                continue
            sample_count = len(rows)
            first_seen = min(r["ts"] for r in rows)
            last_seen = max(r["ts"] for r in rows)
            centroid_conf = sum(self._safe_float(r.get("confidence")) for r in rows) / sample_count
            centroid_adx = sum(self._safe_float(r.get("adx")) for r in rows) / sample_count
            rejection_rate = 1.0
            cluster_id = f"{regime}:{path_hash}"
            label = f"{regime.upper()}::{rows[0]['path'][0] if rows[0]['path'] else 'empty'}"
            new_clusters[(path_hash, regime)] = {
                "cluster_id": cluster_id,
                "trace_path": list(rows[0].get("path") or []),
                "regime": regime,
                "sample_count": sample_count,
                "first_seen": datetime.fromtimestamp(first_seen, tz=timezone.utc).isoformat(),
                "last_seen": datetime.fromtimestamp(last_seen, tz=timezone.utc).isoformat(),
                "rejection_rate": rejection_rate,
                "centroid_confidence": centroid_conf,
                "centroid_adx": centroid_adx,
                "label": label,
            }
        self._clusters = new_clusters

    def get_top_failure_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return top clustered failure patterns sorted by severity + frequency."""
        with self._lock:
            rows = list(self._clusters.values())
        rows.sort(key=lambda x: (self._safe_float(x.get("rejection_rate")), int(x.get("sample_count", 0))), reverse=True)
        return rows[: max(1, int(limit))]

    def _persist_clusters_to_postgres(self, clusters: Dict[Tuple[str, str], Dict[str, Any]]) -> None:
        postgres_url = (os.getenv("NIJA_EIL_POSTGRES_URL", "") or "").strip()
        if not postgres_url or not clusters:
            return

        try:
            import psycopg2
        except Exception:
            return

        try:
            with psycopg2.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    for row in clusters.values():
                        cur.execute(
                            """
                            INSERT INTO failure_clusters (
                                cluster_id, trace_path, regime, sample_count,
                                first_seen, last_seen, rejection_rate,
                                centroid_confidence, centroid_adx, label
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            ON CONFLICT (cluster_id) DO UPDATE SET
                                sample_count = EXCLUDED.sample_count,
                                last_seen = EXCLUDED.last_seen,
                                rejection_rate = EXCLUDED.rejection_rate,
                                centroid_confidence = EXCLUDED.centroid_confidence,
                                centroid_adx = EXCLUDED.centroid_adx,
                                label = EXCLUDED.label
                            """,
                            (
                                row["cluster_id"],
                                row["trace_path"],
                                row["regime"],
                                int(row["sample_count"]),
                                row["first_seen"],
                                row["last_seen"],
                                float(row["rejection_rate"]),
                                float(row["centroid_confidence"]),
                                float(row["centroid_adx"]),
                                row["label"],
                            ),
                        )
                conn.commit()
        except Exception:
            logger.debug("Failure cluster persistence skipped", exc_info=True)

    def _emit_feedback_if_needed(self) -> None:
        if str(os.getenv("NIJA_EIL_GATE_FEEDBACK_ENABLED", "false")).lower() not in ("1", "true", "yes"):
            return

        now = time.time()
        cooldown_sec = 6 * 60 * 60
        for row in self.get_top_failure_patterns(limit=5):
            regime = str(row.get("regime") or "unknown")
            if float(row.get("rejection_rate", 0.0)) < 0.80:
                continue
            if int(row.get("sample_count", 0)) < 5:
                continue
            last_bump = self._regime_feedback_bumped_at.get(regime, 0.0)
            if now - last_bump < cooldown_sec:
                continue
            try:
                try:
                    from bot.ai_entry_gate import BASE_ENTRY_SCORE_THRESHOLD, set_gate_pass_threshold
                except ImportError:
                    from ai_entry_gate import BASE_ENTRY_SCORE_THRESHOLD, set_gate_pass_threshold  # type: ignore[import]
                set_gate_pass_threshold(float(BASE_ENTRY_SCORE_THRESHOLD) + 0.2)
                self._regime_feedback_bumped_at[regime] = now
                logger.warning(
                    "EIL cluster feedback tightened AI gate threshold for regime=%s cluster=%s",
                    regime,
                    row.get("cluster_id"),
                )
            except Exception:
                logger.debug("EIL gate feedback hook skipped", exc_info=True)


_singleton: Optional[FailureClusterEngine] = None
_singleton_lock = threading.Lock()


def get_failure_cluster_engine() -> FailureClusterEngine:
    """Return singleton FailureClusterEngine."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = FailureClusterEngine()
    return _singleton
