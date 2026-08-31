from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_ENTRY = ROOT / "bot" / "bot.py"
PATCH = ROOT / "bot" / "runtime_kraken_precore_liveness_v318_patch.py"


def test_v318_is_in_canonical_fast_guard_bundle_before_bot_main_handoff() -> None:
    text = BOT_ENTRY.read_text(encoding="utf-8")
    guard = '("bot.runtime_kraken_precore_liveness_v318_patch", "KRAKEN_PRECORE_LIVENESS_V318")'
    assert guard in text
    assert text.index(guard) < text.index("from bot.bot_main import main")
    assert text.index('("bot.position_sync_failure_truth_v98_patch", "POSITION_SYNC_FAILURE_TRUTH_V98")') < text.index(guard)


def test_v318_precore_path_is_patch_only_and_has_no_direct_broker_io_calls() -> None:
    text = PATCH.read_text(encoding="utf-8")
    tree = ast.parse(text)

    assert "_patch_all" in text
    assert "_ensure_monitor" not in text
    assert "reconcile_once()" not in text
    assert "get_positions(" not in text
    assert "_kraken_private_call(" not in text
    assert "connect(" not in text

    required_order = (
        "runtime_kraken_transport_timeout_v292_patch",
        "runtime_kraken_credential_lock_scope_v293_patch",
        "runtime_kraken_monitoring_fairness_v297_patch",
        "runtime_kraken_credential_read_convergence_v299_patch",
        "runtime_kraken_balance_epoch_handoff_v312_patch",
        "runtime_kraken_cost_basis_bulk_v288_patch",
        "runtime_kraken_authoritative_snapshot_ownership_v305_patch",
    )
    positions = [text.index(name) for name in required_order]
    assert positions == sorted(positions)

    # v288 chains v304 and v305 chains v306. The pre-core certificate must
    # explicitly prove all four phase surfaces rather than merely importing
    # their modules.
    for flag in (
        "NIJA_RUNTIME_KRAKEN_COST_BASIS_BULK_V288_READY",
        "NIJA_RUNTIME_KRAKEN_COST_BASIS_HISTORY_PAGINATION_V304_READY",
        "NIJA_RUNTIME_KRAKEN_AUTHORITATIVE_SNAPSHOT_OWNERSHIP_V305_READY",
        "NIJA_RUNTIME_KRAKEN_STARTUP_PHASE_HANDOFF_V306_READY",
    ):
        assert flag in text
    assert "v288_resolver_patch_missing" in text
    assert "v306_authoritative_handoff_patch_missing" in text
    assert "redundant_balance_during_history_blocked=true" in text

    # The source must require writer-first attestations and explicitly preserve
    # the no-monitor/no-direct-I/O contract before reporting readiness.
    assert "NIJA_CANONICAL_WRITER_FIRST_V59_READY" in text
    assert "NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY" in text
    assert "v286_monitor_started_by_v318=false" in text
    assert "broker_io=false" in text

    # Keep the parse result used so accidental syntax damage fails this test.
    assert isinstance(tree, ast.Module)
