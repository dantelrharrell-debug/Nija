from __future__ import annotations

import ast
from pathlib import Path


def test_kraken_supervision_chain_references_existing_bot_modules():
    """Every explicit bot module imported by the Kraken supervision chain must exist.

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

    assert referenced, "Kraken supervision chain should explicitly reference runtime modules"

    missing = sorted(
        name
        for name in referenced
        if not (repo_root / "bot" / f"{name}.py").is_file()
        and not (repo_root / "bot" / name / "__init__.py").is_file()
    )
    assert missing == [], f"Production convergence references missing bot modules: {missing}"


def test_transport_timeout_v292_is_in_production_chain():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "bot" / "production_runtime_convergence_v88_patch.py").read_text(encoding="utf-8")
    assert "runtime_kraken_transport_timeout_v292_patch" in source
    assert "runtime_account_scoped_reconciliation_truth_v291_patch" not in source
