from __future__ import annotations

import os

from bot import runtime_all_account_coverage_liveness_v283_patch as v283
from bot import runtime_post_import_convergence_patch as post_import


def _reset(monkeypatch):
    monkeypatch.setattr(v283, "_LAST_LOG_SIGNATURE", "")
    monkeypatch.delenv("NIJA_ALL_ACCOUNT_COVERAGE_LIVENESS_V283_READY", raising=False)
    monkeypatch.delenv("NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY", raising=False)


def test_pending_v281_truth_is_valid_operational_audit(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(v283, "_register_manifest", lambda: True)
    monkeypatch.setattr(
        v283,
        "audit_once",
        lambda: {
            "ready": False,
            "expected_accounts": ("platform:kraken", "user:u1:kraken"),
            "pending": {"user:u1:kraken": ("authoritative_position_fetch_unproven",)},
            "positions": (),
        },
    )

    # v283 means the audit machinery is live, not that coverage itself is green.
    assert v283.install() is True
    assert os.environ["NIJA_ALL_ACCOUNT_COVERAGE_LIVENESS_V283_READY"] == "1"


def test_audit_failure_revokes_coverage_and_v283_capability(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(v283, "_register_manifest", lambda: True)
    monkeypatch.setenv("NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY", "1")

    def boom():
        raise RuntimeError("audit_unavailable")

    monkeypatch.setattr(v283, "audit_once", boom)

    assert v283.install() is False
    assert os.environ["NIJA_ALL_ACCOUNT_COVERAGE_LIVENESS_V283_READY"] == "0"
    assert os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY"] == "0"


def test_manifest_failure_keeps_capability_fail_closed(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(v283, "_register_manifest", lambda: False)
    monkeypatch.setattr(
        v283,
        "audit_once",
        lambda: {"ready": True, "expected_accounts": ("platform:coinbase",), "pending": {}},
    )

    assert v283.install() is False
    assert os.environ["NIJA_ALL_ACCOUNT_COVERAGE_LIVENESS_V283_READY"] == "0"


def test_result_counts_handles_normal_and_malformed_values():
    assert v283._result_counts({"expected_accounts": ("a", "b"), "pending": {"b": ("x",)}}) == (2, 1)
    assert v283._result_counts({"expected_accounts": None, "pending": None}) == (0, 0)


def test_post_import_orders_v283_after_registry_liveness_repairs(monkeypatch):
    order = []

    # Keep the test focused on ordering of the liveness/certification stages.
    monkeypatch.setattr(post_import, "_canonicalize_alias", lambda: False)
    monkeypatch.setattr(post_import, "_apply_broker_threshold", lambda: 1)
    monkeypatch.setattr(post_import, "_patch_quiescence_audit", lambda: True)

    for name in (
        "_install_v154_recovery", "_install_v155_nonce_maturity", "_install_v157_runtime_quality",
        "_install_v158_capital_margin", "_install_v161_capital_position_convergence",
        "_install_v162_late_observation_fence", "_install_v163_activation_convergence",
        "_install_v164_capital_publication_liveness", "_install_v165_capital_publication_scheduling",
        "_install_v167_refresh_demand", "_install_v209_zero_balance_completeness",
        "_install_v224_exchange_reject_provenance", "_install_v228_exchange_reject_dispatch_provenance",
        "_install_v229_capital_provenance_alias", "_install_v232_heartbeat_execution_quality",
        "_install_v233_heartbeat_terminal_authority", "_install_v234_kraken_read_lock_recovery",
        "_install_v236_heartbeat_final_submit", "_install_v237_kraken_local_contention_health",
        "_install_v238_heartbeat_marker_convergence", "_install_v239_all_account_profit_targets",
        "_install_v240_heartbeat_terminal_lifecycle", "_install_v241_kraken_local_contention_alias",
        "_install_v242_kraken_local_contention_instance", "_install_v244_heartbeat_broker_manager_terminal",
        "_install_v263_heartbeat_state_machine_gate",
    ):
        monkeypatch.setattr(post_import, name, lambda: True)

    monkeypatch.setattr(post_import, "_install_v267_capital_position_liveness", lambda: order.append("v267") or True)
    monkeypatch.setattr(post_import, "_install_v268_platform_kraken_registry_liveness", lambda: order.append("v268") or True)
    monkeypatch.setattr(post_import, "_install_v284_platform_object_liveness", lambda: order.append("v284") or True)
    monkeypatch.setattr(post_import, "_install_v280_platform_activation_liveness", lambda: order.append("v280") or True)
    monkeypatch.setattr(post_import, "_install_v283_all_account_coverage_liveness", lambda: order.append("v283") or True)

    assert post_import._iteration() is True
    assert order == ["v267", "v268", "v284", "v280", "v283"]
    assert post_import._LAST_PREREQUISITES["v284_platform_object_liveness"] is True
    assert post_import._LAST_PREREQUISITES["v283_all_account_coverage_liveness"] is True
