#!/usr/bin/env python3
"""Align activation heartbeat verification with canonical execution proof (v402).

Production evidence on 2026-09-08 showed the activation circuit breaker reading a
stale heartbeat verification file while v238/v347 had already verified the
canonical v169 execution marker as fresh.  This is a split-source liveness bug,
not a reason to weaken execution freshness.

v402 keeps the existing heartbeat marker as the primary source.  Only when that
source is stale/missing does it allow the *same* activation freshness policy to
be satisfied by the canonical v169 execution marker, and only when that marker:
- is JSON and stage-sufficient,
- has source heartbeat_trade or canonical_confirmed_fill,
- has proof_kind=execution_probe,
- has a positive verified timestamp,
- passes v169 execution provenance validation when available, and
- is no older than the unchanged HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS.

No marker is written or refreshed. No breaker threshold is changed. No order is
submitted/cancelled. Writer, nonce, capital, position-sync, risk, kill-switch,
ECEL, minimum-order, confirmed-fill, and protective-exit gates remain unchanged.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "trading_state_machine.py"
MARKER = "20260908-execution-verification-source-alignment-v402"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("EXECUTION_VERIFICATION_SOURCE_ALIGNMENT_V402_ALREADY_APPLIED")
        return

    anchor = '''def _heartbeat_verified() -> bool:\n'''
    if anchor not in text:
        raise RuntimeError("v402 heartbeat_verified anchor not found")

    block = r'''# 20260908-execution-verification-source-alignment-v402
_heartbeat_verification_status_pre_v402 = _heartbeat_verification_status


def _canonical_execution_verification_status_v402() -> tuple[bool, str, Dict[str, Any]]:
    """Read-only fallback to the canonical v169 execution marker."""
    try:
        try:
            from bot import runtime_execution_capital_integrity_v169_patch as v169
        except ImportError:
            import runtime_execution_capital_integrity_v169_patch as v169  # type: ignore[import]

        path_fn = getattr(v169, "_execution_marker_path", None)
        provenance_fn = getattr(v169, "_execution_provenance_valid", None)
        if not callable(path_fn):
            return False, "canonical_execution_marker_path_unavailable_v402", {}

        marker = path_fn()
        if not marker.exists():
            return False, "canonical_execution_marker_missing_v402", {"path": str(marker)}
        raw = marker.read_text(encoding="utf-8").strip()
        if not raw.startswith("{"):
            return False, "canonical_execution_marker_non_json_v402", {"path": str(marker)}
        payload = json.loads(raw)

        stage = str(payload.get("stage", "AUTH_VERIFY") or "AUTH_VERIFY").strip().upper()
        required_stage = _heartbeat_min_required_stage()
        if stage not in _HEARTBEAT_STAGE_ORDER:
            return False, f"canonical_execution_marker_invalid_stage_v402:{stage}", {"path": str(marker)}
        if _HEARTBEAT_STAGE_ORDER[stage] < _HEARTBEAT_STAGE_ORDER[required_stage]:
            return False, f"canonical_execution_stage_too_low_v402:{stage}<{required_stage}", {"path": str(marker)}

        source = str(payload.get("source", "") or "").strip().lower()
        kind = str(payload.get("proof_kind", "") or "").strip().lower()
        if source not in {"heartbeat_trade", "canonical_confirmed_fill"} or kind != "execution_probe":
            return False, (
                "canonical_execution_provenance_invalid_v402:"
                f"source={source or 'missing'}:kind={kind or 'missing'}"
            ), {"path": str(marker), "stage": stage}

        if callable(provenance_fn):
            provenance_ok, provenance_detail = provenance_fn(dict(payload), required_stage)
            if not provenance_ok:
                return False, f"canonical_execution_provenance_rejected_v402:{provenance_detail}", {
                    "path": str(marker), "stage": stage, "source": source
                }

        try:
            verified_at = float(
                payload.get("verified_at_epoch")
                or payload.get("verified_at")
                or payload.get("timestamp_epoch")
                or 0.0
            )
        except (TypeError, ValueError):
            verified_at = 0.0
        if verified_at <= 0.0:
            return False, "canonical_execution_marker_timestamp_missing_v402", {"path": str(marker)}

        max_age_s = _heartbeat_verification_max_age_seconds()
        age_s = max(0.0, time.time() - verified_at)
        if max_age_s > 0.0 and age_s > max_age_s:
            return False, (
                f"canonical_execution_verification_stale_v402 age_s={age_s:.1f} "
                f"max_age_s={max_age_s:.1f}"
            ), {
                "path": str(marker), "required_stage": required_stage, "stage": stage,
                "verified_at_epoch": verified_at, "age_s": age_s, "max_age_s": max_age_s,
                "source": source, "proof_kind": kind,
            }

        return True, "", {
            "path": str(marker), "required_stage": required_stage, "stage": stage,
            "verified_at_epoch": verified_at, "age_s": age_s, "max_age_s": max_age_s,
            "source": source, "proof_kind": kind,
            "verification_source": "canonical_execution_marker_v402",
        }
    except Exception as exc:
        return False, f"canonical_execution_verification_error_v402:{type(exc).__name__}:{exc}", {}


def _heartbeat_verification_status() -> tuple[bool, str, Dict[str, Any]]:
    primary_ok, primary_detail, primary_meta = _heartbeat_verification_status_pre_v402()
    if primary_ok:
        return primary_ok, primary_detail, primary_meta

    canonical_ok, canonical_detail, canonical_meta = _canonical_execution_verification_status_v402()
    if canonical_ok:
        logger.critical(
            "EXECUTION_VERIFICATION_SOURCE_ALIGNMENT_V402_READY marker=20260908-execution-verification-source-alignment-v402 "
            "primary_detail=%s canonical_source=%s age_s=%.1f max_age_s=%.1f marker_mutated=false "
            "freshness_extended=false breaker_threshold_unchanged=true order_submitted=false "
            "order_cancelled=false execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            str(primary_detail or "unknown"), str(canonical_meta.get("source") or "unknown"),
            float(canonical_meta.get("age_s") or 0.0), float(canonical_meta.get("max_age_s") or 0.0),
        )
        return True, "", canonical_meta

    merged = dict(primary_meta or {})
    merged["canonical_fallback_detail"] = canonical_detail
    return False, primary_detail, merged


'''

    text = text.replace(anchor, block + anchor, 1)
    TARGET.write_text(text, encoding="utf-8")
    print(
        "EXECUTION_VERIFICATION_SOURCE_ALIGNMENT_V402_PATCH_APPLIED "
        f"marker={MARKER} primary_heartbeat_source_preserved=true "
        "canonical_execution_fallback_read_only=true max_age_unchanged=true "
        "breaker_threshold_unchanged=true marker_mutated=false orders_submitted=false "
        "orders_cancelled=false execution_proof_fabricated=false forced_activation=false "
        "safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
