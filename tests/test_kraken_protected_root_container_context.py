"""Verify the signed-root caller survives the existing Docker/shell boundary.

Reuse the network-disabled container fixture without changing its synthetic
credentials, the production Docker recipe, or reviewed source/digest pins.
"""
from unittest.mock import patch

import test_render_container_startup as container


_ANCHOR = '    print("ISOLATED_STARTUP_BOUNDARY_REACHED runtime_started=false orders_submitted=false")'
_CHECKS = '''
    import ast
    from pathlib import Path
    for name in ("kraken_protected_startup_root", "kraken_startup_receipts",
                 "kraken_startup_evidence_binding", "kraken_canonical_startup_factory"):
        path = Path("/app/bot") / (name + ".py")
        compile(path.read_bytes(), str(path), "exec")
    tree = ast.parse(Path("/app/bot/bot_main.py").read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = {node.func.id: node.lineno for node in ast.walk(main)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert calls["_publish_canonical_strategy_for_runtime"] < calls["register_from_protected_root"]
    assert calls["register_from_protected_root"] < calls["install_from_canonical_startup"]
    assert calls["install_from_canonical_startup"] < calls["start_trading_engine"]
'''


def _protected_probe() -> str:
    if container.CONTAINER_PROBE.count(_ANCHOR) != 1:
        raise AssertionError("offline startup probe boundary changed")
    return container.CONTAINER_PROBE.replace(_ANCHOR, _CHECKS + "\n" + _ANCHOR, 1)


class ProtectedRootContainerStartupTests(container.RenderContainerStartupTests):
    """Run real source patchers, then inspect packaged caller order, never trade."""

    def _assert_startup(self, entrypoint: str) -> None:
        with patch.object(container, "CONTAINER_PROBE", _protected_probe()):
            super()._assert_startup(entrypoint)
