"""Build-patch compatibility must preserve IDs and fail on unknown code."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("patch_v391", ROOT / "scripts/apply_protection_binding_precision_v391.py")
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


@pytest.mark.parametrize("hardened", [True, False])
def test_known_source_variants_preserve_deterministic_ids_and_patch_once(tmp_path, monkeypatch, hardened):
    source = (ROOT / "bot/runtime_kraken_native_margin_backup_v380_patch.py").read_text()
    if not hardened:
        source = source.replace(', usedforsecurity=False', '')
    target = tmp_path / "native.py"
    target.write_text(source)
    monkeypatch.setattr(patcher, "NATIVE", target)
    assert patcher.patch_native_client_id_recovery()
    patched = target.read_text()
    assert not patcher.patch_native_client_id_recovery()
    assert target.read_text() == patched
    # Compile/extract identifier function only: no broker imports or transport.
    import ast
    tree = ast.parse(patched)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_client_id")
    scope = {"hashlib": hashlib, "_PREFIX_SL": "njsl", "_PREFIX_TP": "njtp"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "offline", "exec"), scope)
    for leg in ("stop-loss", "take-profit"):
        prefix = "njsl" if leg == "stop-loss" else "njtp"
        expected = prefix + hashlib.sha1(b"offline-account|ETH-USD", usedforsecurity=False).hexdigest()[:12]
        assert scope["_client_id"]("offline-account", "ETH-USD", leg) == expected


def test_unknown_client_id_implementation_fails_without_partial_write(tmp_path, monkeypatch):
    source = (ROOT / "bot/runtime_kraken_native_margin_backup_v380_patch.py").read_text()
    source = source.replace('hexdigest()[:12]', 'hexdigest()[:11]')
    target = tmp_path / "native.py"
    target.write_text(source)
    monkeypatch.setattr(patcher, "NATIVE", target)
    with pytest.raises(RuntimeError, match="_client_id anchor"):
        patcher.patch_native_client_id_recovery()
    assert target.read_text() == source
