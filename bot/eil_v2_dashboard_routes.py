"""Dashboard data helpers for Execution Intelligence Layer v2."""

from __future__ import annotations

from typing import Any, Dict


def collect_eil_v2_snapshot() -> Dict[str, Any]:
    """Collect EIL v2 summary snapshot for dashboard/API use."""
    snapshot: Dict[str, Any] = {
        "available": True,
        "failure_clusters": {"available": False, "patterns": []},
        "quality_scorer": {"available": False},
        "regime_gate": {"available": False, "heatmap": {}},
    }

    try:
        from bot.failure_cluster_engine import get_failure_cluster_engine

        engine = get_failure_cluster_engine()
        snapshot["failure_clusters"] = {
            "available": True,
            "patterns": engine.get_top_failure_patterns(limit=10),
        }
    except Exception as exc:
        snapshot["failure_clusters"] = {"available": False, "error": str(exc), "patterns": []}

    try:
        from bot.trace_quality_scorer import get_trace_quality_scorer

        scorer = get_trace_quality_scorer()
        snapshot["quality_scorer"] = {
            "available": True,
            "status": scorer.get_model_status() if hasattr(scorer, "get_model_status") else {},
        }
    except Exception as exc:
        snapshot["quality_scorer"] = {"available": False, "error": str(exc)}

    try:
        from bot.regime_gate_calibrator import get_regime_gate_calibrator

        calibrator = get_regime_gate_calibrator()
        snapshot["regime_gate"] = {
            "available": True,
            "heatmap": calibrator.get_regime_heatmap() if hasattr(calibrator, "get_regime_heatmap") else {},
        }
    except Exception as exc:
        snapshot["regime_gate"] = {"available": False, "error": str(exc), "heatmap": {}}

    return snapshot
