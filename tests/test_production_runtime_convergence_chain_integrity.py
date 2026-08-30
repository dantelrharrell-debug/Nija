from __future__ import annotations

import ast
from pathlib import Path


def test_kraken_supervision_chain_references_existing_bot_modules():
    """Every explicit bot module imported by the runtime supervision chain must exist.

    This is intentionally a static check: it catches merge/version-cleanup mistakes
    without importing runtime patches or triggering broker/network/startup side
    effects in the unit-test process.
    """
    repo_root = Path(__file__).resolve().parents[1]
    source_path = repo_root / "bot" / "production_runtime_convergence_v88_patch.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_install_kraken_user_supervision"
    )

    referenced: set[str] = set()
    for node in ast.walk(target):
        if isinstance(node, ast.ImportFrom) and node.module == "bot":
            referenced.update(alias.name for alias in node.names)

    assert referenced, "Runtime supervision chain should explicitly reference runtime modules"

    missing = sorted(
        name
        for name in referenced
        if not (repo_root / "bot" / f"{name}.py").is_file()
        and not (repo_root / "bot" / name / "__init__.py").is_file()
    )
    assert missing == [], f"Production convergence references missing bot modules: {missing}"


def test_transport_isolation_cost_basis_dust_fairness_inflight_credential_read_registered_position_and_heartbeat_bridge_repairs_are_in_production_chain_in_order():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "bot" / "production_runtime_convergence_v88_patch.py").read_text(encoding="utf-8")

    v292 = source.index("runtime_kraken_transport_timeout_v292_patch")
    v293 = source.index("runtime_kraken_credential_lock_scope_v293_patch")
    v294 = source.index("runtime_position_sync_isolation_v294_patch")
    v295 = source.index("runtime_okx_cost_basis_recovery_v295_patch")
    v296 = source.index("runtime_dust_position_policy_convergence_v296_patch")
    v297 = source.index("runtime_kraken_monitoring_fairness_v297_patch")
    v298 = source.index("runtime_kraken_inflight_snapshot_truth_v298_patch")
    v299 = source.index("runtime_kraken_credential_read_convergence_v299_patch")
    v302 = source.index("runtime_registered_platform_position_completeness_v302_patch")
    v303 = source.index("runtime_heartbeat_position_cap_result_bridge_v303_patch")

    assert v292 < v293 < v294 < v295 < v296 < v297 < v298 < v299 < v302 < v303
    assert "runtime_account_scoped_reconciliation_truth_v291_patch" not in source
