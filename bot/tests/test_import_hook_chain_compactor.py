from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_deep_hook_chain_allows_nested_standard_library_imports() -> None:
    """Reproduce the production wrapper stack in a clean isolated interpreter."""

    root = Path(__file__).resolve().parents[2]
    script = r'''
import builtins
import sys

sys.path.insert(0, REPO_ROOT)
import import_hook_recursion_shield_patch as shield

shield.install_import_hook()

# Model the independent NIJA compatibility wrappers shown in the Render
# RecursionError traceback.  Every wrapper captures the prior importer.
for index in range(32):
    previous = builtins.__import__
    def wrapper(name, globals=None, locals=None, fromlist=(), level=0, _previous=previous):
        module = _previous(name, globals, locals, fromlist, level)
        return module
    wrapper.__name__ = f"synthetic_nija_hook_{index}"
    builtins.__import__ = wrapper

shield.compact_import_chain(force_log=True)
sys.setrecursionlimit(300)

# ElementTree performs nested imports.  Before the compact guard, nested imports
# repeatedly traversed every wrapper and exhausted the recursion limit.
import xml.etree.ElementTree as element_tree

assert element_tree.Element("ok").tag == "ok"
assert getattr(builtins.__import__, "_nija_import_chain_compactor", "") == "20260711d"
print("IMPORT_HOOK_CHAIN_COMPACTOR_OK")
'''.replace("REPO_ROOT", repr(str(root)))

    completed = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
    assert "IMPORT_HOOK_CHAIN_COMPACTOR_OK" in completed.stdout
    assert "RecursionError" not in completed.stdout


def test_compactor_source_preserves_fail_closed_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "import_hook_recursion_shield_patch.py").read_text(encoding="utf-8")

    assert "IMPORT_HOOK_RECURSION_RECOVERED" in source
    assert "nested_imports=python_original" in source
    assert "authority_bypass=false" in source
    assert "risk_bypass=false" in source
    assert "builtins.__import__ = guard" in source
