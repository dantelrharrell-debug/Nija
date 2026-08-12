from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "bot" / "final_production_activation_repair_v61_patch.py"
ENTRYPOINT = ROOT / "bot" / "bot.py"


def _source() -> str:
    return PATCH.read_text(encoding="utf-8")


def test_v61_entrypoint_order_precedes_v59_and_v60() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    i58 = text.index("FINAL_PRODUCTION_ACTIVATION_V58")
    i61 = text.index("FINAL_PRODUCTION_ACTIVATION_V61")
    i59 = text.index("FINAL_PRODUCTION_ACTIVATION_V59")
    i60 = text.index("FINAL_PRODUCTION_ACTIVATION_V60")
    assert i58 < i61 < i59 < i60


def test_v61_requires_exact_core_and_running_supervised_before_activation() -> None:
    text = _source()
    assert 'blockers.append("core_registered")' in text
    assert 'blockers.append("core_alive")' in text
    assert 'bootstrap_state != "RUNNING_SUPERVISED"' in text
    assert 'blockers.append(f"bootstrap_state:{bootstrap_state}")' in text
    assert 'blockers.append("writer_epoch_current")' in text


def test_v61_precore_proofs_fail_closed_for_runtime_authority() -> None:
    text = _source()
    assert '"authority_ready": False' in text
    assert '"execution_ready": False' in text
    assert '"nonce_ready": False' in text
    assert '"bootstrap_ready": False' in text
    assert '"strict_authority": "deferred_until_canonical_core_supervised"' in text


def test_v61_revokes_stale_true_readiness_before_live_active() -> None:
    text = _source()
    assert 'prelive = trading_state != "LIVE_ACTIVE"' in text
    assert 'table.revoke_ready(key, reason="v61_current_proof_false")' in text
    assert 'current_pending = [key for key in _KEYS if not bool(proofs.get(key, False))]' in text
    assert 'pending = [key for key in _KEYS if key in current_pending or key in table_pending]' in text
    assert '"PREACTIVATION_READY marker=%s authority_ready=true nonce_ready=true "' in text


def test_v61_guards_both_v60_request_and_commit_boundary() -> None:
    tree = ast.parse(_source())
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "_patch_v60_request_activation" in function_names
    assert "_patch_activation_commit_boundary" in function_names
    text = _source()
    assert 'v60.request_activation = request_activation' in text
    assert 'monitor._commit_once = commit_once' in text
    assert 'ACTIVATION_SINGLE_FLIGHT_DEFERRED' in text


def test_v61_observes_but_never_clears_seak() -> None:
    text = _source()
    assert 'def _seak_status()' in text
    assert 'get_single_execution_authority_kernel' in text
    forbidden = (
        ".resume(",
        "seak.resume",
        "_halt_event.clear",
        "FORCE_TRADE=true",
        "NIJA_FORCE_ACTIVATION=true",
    )
    for token in forbidden:
        assert token not in text


def test_v61_does_not_weaken_strategy_risk_or_nonce_thresholds() -> None:
    text = _source()
    forbidden = (
        "MINIMUM_TRADING_BALANCE =",
        "NIJA_EXECUTION_MIN_CANDLES =",
        "FORCE_LIVE_TRANSITION =",
        "FORCE_TRADE =",
        "NIJA_FORCE_ACTIVATION =",
        "NIJA_ENFORCE_NONCE_WRITER_LEASE=false",
    )
    for token in forbidden:
        assert token not in text


def test_v61_installer_exports_success_marker_and_all_four_guards() -> None:
    text = _source()
    for key in (
        '"proof_collection": _patch_v16_proof_collection()',
        '"readiness_truth": _patch_v16_truth_sync()',
        '"v60_request": _patch_v60_request_activation()',
        '"commit_boundary": _patch_activation_commit_boundary()',
    ):
        assert key in text
    assert 'NIJA_FINAL_PRODUCTION_ACTIVATION_V61_INSTALLED' in text
