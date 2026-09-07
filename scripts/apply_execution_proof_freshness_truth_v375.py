"""Apply NIJA execution-proof freshness truth convergence v375.

Production on 2026-09-06/07 exposed a split-view diagnostic defect: the v238
writer-renewal postwork could log GENUINE_EXECUTION_PROOF_READY while the
activation state machine, in the same runtime window, correctly rejected the
execution marker as older than HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS.

v375 does not refresh, rewrite, extend, recover, or fabricate execution proof.
It wraps v238's existing canonical/provenance verifier with a second read-only
freshness check against v169's canonical execution-marker path and the unchanged
trading-state-machine freshness policy.  A stale/malformed/missing marker is
reported pending and activation reconciliation is not woken by v238.

The same Render startup patcher also applies the v385 ordering-only liveness
repair to v368.  Once four-way Kraken margin protection is genuinely ready,
v372/v373 authenticated execution-proof recovery now runs before the slower
native-backup and registered-user proof bootstrap work.  No readiness bit or
execution marker is written by the ordering repair; the existing v328/v346/v169
canonical proof chain remains the only authority.

This patch never submits an order, enables heartbeat trading, changes the
30-minute default, changes readiness, clears a circuit breaker, forces
activation, or weakens writer/nonce/risk/capital/position/kill-switch/ECEL/
minimum-order/fill/protective-exit gates.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V238_PATH = ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py"
V368_PATH = ROOT / "bot" / "runtime_kraken_margin_protection_authority_v368_patch.py"
MARKER = "20260907-execution-proof-freshness-truth-v375"
ORDER_MARKER = "KRAKEN_MARGIN_EXECUTION_LIVENESS_V385_PRIMED"


def patch_v238_text(text: str) -> str:
    if "DIRECT_EXECUTION_FRESHNESS_V375" in text:
        return text

    anchor = "def _wake_activation_after_genuine_marker(source: str) -> bool:\n"
    if anchor not in text:
        raise RuntimeError("v375 v238 wake anchor missing")

    guard = '''_genuine_execution_marker_ready_pre_v375 = _genuine_execution_marker_ready\n\n\ndef _genuine_execution_marker_ready_v375() -> tuple[bool, str]:\n    \"\"\"Require direct canonical marker freshness before v238 can wake activation.\"\"\"\n    base_ok, base_detail = _genuine_execution_marker_ready_pre_v375()\n    if not base_ok:\n        return False, str(base_detail or \"canonical_execution_proof_not_ready\")\n\n    try:\n        import json as _json\n        import time as _time\n\n        v169 = importlib.import_module(\"bot.runtime_execution_capital_integrity_v169_patch\")\n        tsm = importlib.import_module(\"bot.trading_state_machine\")\n        path_fn = getattr(v169, \"_execution_marker_path\", None)\n        if not callable(path_fn):\n            return False, \"direct_execution_marker_path_unavailable_v375\"\n\n        path = path_fn()\n        raw = path.read_text(encoding=\"utf-8\").strip()\n        if not raw.startswith(\"{\"):\n            return False, \"direct_execution_marker_non_json_v375\"\n        payload = _json.loads(raw)\n\n        source = str(payload.get(\"source\", \"\") or \"\").strip().lower()\n        kind = str(payload.get(\"proof_kind\", \"\") or \"\").strip().lower()\n        if source not in {\"heartbeat_trade\", \"canonical_confirmed_fill\"} or kind != \"execution_probe\":\n            return False, (\n                \"direct_execution_provenance_invalid_v375:\"\n                f\"source={source or 'missing'}:kind={kind or 'missing'}\"\n            )\n\n        try:\n            verified_at = float(\n                payload.get(\"verified_at_epoch\")\n                or payload.get(\"verified_at\")\n                or payload.get(\"timestamp_epoch\")\n                or 0.0\n            )\n        except (TypeError, ValueError):\n            verified_at = 0.0\n        if verified_at <= 0.0:\n            return False, \"direct_execution_marker_timestamp_missing_v375\"\n\n        max_age_fn = getattr(tsm, \"_heartbeat_verification_max_age_seconds\", None)\n        if callable(max_age_fn):\n            max_age_s = max(0.0, float(max_age_fn()))\n        else:\n            try:\n                max_age_s = max(\n                    0.0,\n                    float(os.environ.get(\"HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS\", \"1800\") or \"1800\"),\n                )\n            except (TypeError, ValueError):\n                max_age_s = 1800.0\n\n        age_s = max(0.0, _time.time() - verified_at)\n        if max_age_s > 0.0 and age_s > max_age_s:\n            return False, (\n                \"DIRECT_EXECUTION_FRESHNESS_V375_STALE \"\n                f\"age_s={age_s:.1f} max_age_s={max_age_s:.1f} source={source}\"\n            )\n        return True, (\n            \"DIRECT_EXECUTION_FRESHNESS_V375_READY \"\n            f\"age_s={age_s:.1f} max_age_s={max_age_s:.1f} source={source}\"\n        )\n    except FileNotFoundError:\n        return False, \"direct_execution_marker_missing_v375\"\n    except Exception as exc:\n        return False, f\"direct_execution_freshness_error_v375:{type(exc).__name__}:{exc}\"\n\n\n_genuine_execution_marker_ready = _genuine_execution_marker_ready_v375\n\n\n'''

    text = text.replace(anchor, guard + anchor, 1)
    if "DIRECT_EXECUTION_FRESHNESS_V375_STALE" not in text:
        raise RuntimeError("v375 freshness guard insertion failed")
    return text


def patch_v368_text(text: str) -> str:
    """Move authenticated v372/v373 recovery ahead of slow post-ready backup work."""
    if ORDER_MARKER in text:
        return text

    function_anchor = "def _post_ready_liveness_worker() -> None:\n"
    native_anchor = "    native_ready = _install_native_backup_v381()\n"
    proof_anchor = "    v372_ready = _install_v372()\n"
    wake_anchor = "    _wake_runtime()\n"

    function_pos = text.find(function_anchor)
    if function_pos < 0:
        raise RuntimeError("v385 v368 post-ready worker anchor missing")
    native_pos = text.find(native_anchor, function_pos)
    if native_pos < 0:
        raise RuntimeError("v385 v368 native-backup anchor missing")
    proof_pos = text.find(proof_anchor, native_pos)
    if proof_pos < 0:
        raise RuntimeError("v385 v368 v372 proof anchor missing")
    wake_pos = text.find(wake_anchor, proof_pos)
    if wake_pos < 0:
        raise RuntimeError("v385 v368 wake anchor missing")
    wake_end = wake_pos + len(wake_anchor)

    proof_block = text[proof_pos:wake_end]
    without_late_block = text[:proof_pos] + text[wake_end:]
    native_pos = without_late_block.find(native_anchor, function_pos)
    if native_pos < 0:
        raise RuntimeError("v385 v368 native-backup anchor lost during reorder")

    primed_block = (
        f"    # {ORDER_MARKER}: authenticated execution recovery must not wait behind slow backup I/O.\n"
        + proof_block
        + "\n"
    )
    patched = without_late_block[:native_pos] + primed_block + without_late_block[native_pos:]

    if patched.find(proof_anchor, function_pos) > patched.find(native_anchor, function_pos):
        raise RuntimeError("v385 execution recovery reorder failed")
    if patched.count(proof_anchor) != text.count(proof_anchor):
        raise RuntimeError("v385 execution recovery block duplication detected")
    return patched


def main() -> None:
    original = V238_PATH.read_text(encoding="utf-8")
    patched = patch_v238_text(original)
    if patched != original:
        V238_PATH.write_text(patched, encoding="utf-8")

    v368_original = V368_PATH.read_text(encoding="utf-8")
    v368_patched = patch_v368_text(v368_original)
    if v368_patched != v368_original:
        V368_PATH.write_text(v368_patched, encoding="utf-8")

    print(
        "EXECUTION_PROOF_FRESHNESS_TRUTH_V375_APPLIED "
        f"marker={MARKER} direct_marker_freshness_required=true "
        "kraken_margin_execution_liveness_v385=primed_before_native_backup "
        "marker_mutated=false max_age_unchanged=true no_order_submitted=true "
        "heartbeat_orders_enabled=false readiness_written=false forced_activation=false "
        "safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
